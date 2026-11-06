#!/usr/bin/env python3
"""Self-service portal, worker side (see docs/self-service.md). Runs on mgmt01 as root.

Every few seconds it takes all waiting requests (from the web side, portal.py) as one
batch:

  1. assigns each new machine a free slot and writes inventory/guests/<host>.yml,
     or deletes that file for a removal,
  2. commits and pushes the batch to GitHub (the deploy key in /root/.ssh),
  3. runs `lab apply` once for the whole batch (and `lab prune` after removals).

Progress after that comes from mgmt01's nginx access log, followed in a thread: each
guest machine fetches its install record, then its one-time join password, and at the
end of every configuration run it requests /lab-events/configured. Guest machines have
fixed addresses, so the client IP says which machine it is.

Status lives in /var/lib/lab-portal/machines/<user>.json, which the web side reads.
"""
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path("/opt/proxmox-lab")
GUESTS = REPO / "inventory" / "guests"
STATE = Path("/var/lib/lab-portal")
REQUESTS, MACHINES, PASSWORDS = STATE / "requests", STATE / "machines", STATE / "passwords"
LOGS = Path("/var/log/lab-portal")
ACCESS_LOG = Path("/var/log/nginx/access.log")
MAX_GUESTS = int(os.environ.get("LAB_PORTAL_MAX_GUESTS", "4"))
DC = ["ssh", "-n", "-o", "BatchMode=yes", "jrhodes@10.10.10.5"]   # the runner key from `lab`
GIT_ID = ["-c", "user.name=Lab portal", "-c", "user.email=lab-portal@mgmt01.ad.lab.internal"]

lock = threading.Lock()   # machine files are written by the batch loop and the log follower


def slot_values(n):
    """Guest machines use slots 1-9 (docs/self-service.md)."""
    return {"vmid": 130 + n, "ip": f"10.10.10.{30 + n}", "mac": f"BC:24:11:00:00:{30 + n}"}


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- machine status files

def load(user):
    try:
        return json.loads((MACHINES / f"{user}.json").read_text())
    except (OSError, ValueError):
        return None


def save(m):
    path = MACHINES / f"{m['user']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1))
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def mark(user, phase=None, **fields):
    """Record a phase (only the first time it happens) and/or other fields."""
    with lock:
        m = load(user)
        if not m:
            return
        if phase and phase not in m["phases"]:
            m["phases"][phase] = time.time()
            log(f"{m['host']}: {phase}")
        m.update(fields)
        save(m)


def never_built(m):
    """Rejected before anything was committed: nothing exists in git, AD or Proxmox."""
    return m["state"] == "failed" and "recorded" not in m["phases"]


def all_machines():
    return [m for p in MACHINES.glob("*.json") if (m := load(p.stem))]


# ---------------------------------------------------------------- shell helpers

def run(cmd, logfile=None, on_line=None, **kw):
    """Run a command, optionally teeing its output to a log file line by line."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    tail = []
    for line in proc.stdout:
        if logfile:
            logfile.write(line)
            logfile.flush()
        tail = (tail + [line.rstrip()])[-15:]
        if on_line:
            on_line(line)
    return proc.wait(), "\n".join(tail)


def git(*args):
    return subprocess.run(["git", *GIT_ID, *args], cwd=REPO, capture_output=True, text=True)


def ad_user_exists(user):
    return subprocess.run(DC + [f"sudo samba-tool user show {user}"], capture_output=True).returncode == 0


def taken_slots():
    used = set()
    for f in GUESTS.glob("*.yml"):
        m = re.search(r"vmid:\s*(\d+)", f.read_text())
        if m:
            used.add(int(m.group(1)) - 130)
    return used


# ---------------------------------------------------------------- one batch

def take_requests():
    reqs = []
    for path in sorted(REQUESTS.glob("*.json")):
        try:
            reqs.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass
        path.unlink(missing_ok=True)
    return reqs


def reject(req, why):
    """A create request the worker can't fulfil. The web side shows the error."""
    log(f"rejected {req['user']}: {why}")
    m = {"user": req["user"], "role": req["role"], "host": f"ws-{req['user']}", "ip": "",
         "token_sha256": req["token_sha256"], "state": "failed", "error": why,
         "phases": {"queued": req["time"]}}
    with lock:
        save(m)
    (PASSWORDS / req["user"]).unlink(missing_ok=True)


def batch(reqs):
    git("fetch", "-q", "origin")
    git("reset", "-q", "--hard", "origin/main")   # the runner's checkout never carries local edits
    creates, removes, used = [], [], taken_slots()

    for req in reqs:
        user = req["user"]
        if req["action"] == "create":
            old = load(user)
            if old and not never_built(old):
                continue                                    # already handled
            if ad_user_exists(user):
                reject(req, f"an account called '{user}' already exists in AD")
                continue
            free = [n for n in range(1, 10) if n not in used]
            if not free or len(used) >= MAX_GUESTS:
                reject(req, f"the lab is full ({MAX_GUESTS} guest workstations)")
                continue
            n = free[0]
            used.add(n)
            s, host = slot_values(n), f"ws-{user}"
            (GUESTS / f"{host}.yml").write_text(
                f'{host}: {{ vmid: {s["vmid"]}, mac: "{s["mac"]}", ip: {s["ip"]}, '
                f'role: {req["role"]}, owner: {user} }}\n')
            with lock:
                save({"user": user, "role": req["role"], "host": host, "ip": s["ip"], "vmid": s["vmid"],
                      "token_sha256": req["token_sha256"], "state": "building", "error": None,
                      "phases": {"queued": req["time"]}})
            creates.append(user)
        elif req["action"] == "delete":
            m = load(user)
            if not m or m.get("token_sha256") != req["token_sha256"]:
                continue
            if never_built(m):                              # rejected: nothing in git or AD
                (MACHINES / f"{user}.json").unlink(missing_ok=True)
                (PASSWORDS / user).unlink(missing_ok=True)
                continue
            (GUESTS / f"{m['host']}.yml").unlink(missing_ok=True)
            mark(user, state="removing")
            removes.append(user)

    if not creates and not removes:
        return
    parts = [f"add ws-{u} ({load(u)['role']}, owner {u})" for u in creates] + [f"remove ws-{u}" for u in removes]
    git("add", "-A", "inventory/guests")
    result = git("commit", "-q", "-m", "Portal: " + "; ".join(parts))
    if result.returncode == 0:
        result = git("push", "-q", "origin", "HEAD:main")
    if result.returncode != 0:
        why = "could not commit the request to git"
        log(f"{why}: {result.stdout}{result.stderr}")
        for u in creates:
            mark(u, state="failed", error=why)
        return
    for u in creates:
        mark(u, "recorded")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    host_of = {f"ws-{u}": u for u in creates}

    def follow(line):   # OpenTofu's progress lines name each VM
        m = re.search(r'workstation\["(ws-[a-z0-9]+)"\]: (Creating|Creation complete)', line)
        if m and m.group(1) in host_of:
            # infra.yml and otp.yml run before OpenTofu, so identity is done once it starts
            mark(host_of[m.group(1)], "identity")
            if m.group(2) == "Creation complete":
                mark(host_of[m.group(1)], "created")

    env = {**os.environ, "LAB_YES": "1"}
    with open(LOGS / f"{stamp}-apply.log", "w") as f:
        rc, tail = run(["lab", "apply"], f, follow, env=env)
    if rc != 0:
        for u in creates:
            if "created" not in (load(u) or {}).get("phases", {}):
                mark(u, state="failed", error=f"lab apply failed (log {stamp}-apply.log)")
        log(f"lab apply failed:\n{tail}")

    if removes:
        with open(LOGS / f"{stamp}-prune.log", "w") as f:
            rc, tail = run(["lab", "prune"], f, env=env)
        for u in removes:
            if rc == 0:
                (MACHINES / f"{u}.json").unlink(missing_ok=True)
                (PASSWORDS / u).unlink(missing_ok=True)
                log(f"removed ws-{u}")
            else:
                mark(u, state="failed", error=f"removal failed (log {stamp}-prune.log)")


# ---------------------------------------------------------------- nginx log follower

LINE = re.compile(r'^(\S+) \S+ \S+ \[[^\]]+\] "GET (\S+) [^"]*" (\d{3})')


def follow_access_log():
    """tail -F: keep reading new lines, reopen when logrotate replaces the file."""
    f, inode, first = None, None, True
    while True:
        try:
            st = ACCESS_LOG.stat()
            if f is None or st.st_ino != inode:
                if f:
                    f.close()
                f, inode = open(ACCESS_LOG), st.st_ino
                if first:                    # at startup, skip history; after a rotation, read all
                    f.seek(0, os.SEEK_END)
                    first = False
            line = f.readline()
            if not line:
                time.sleep(1)
                continue
            m = LINE.match(line)
            if not m or m.group(3) not in ("200", "204"):
                continue
            ip, path = m.group(1), m.group(2)
            for mach in all_machines():
                if mach.get("ip") != ip or mach.get("state") != "building":
                    continue
                if path.endswith("/user-data"):
                    mark(mach["user"], "installing")
                elif path.endswith("/otp"):
                    mark(mach["user"], "installed")
                elif path == "/lab-events/configured":
                    mark(mach["user"], "ready", state="ready")
        except FileNotFoundError:
            time.sleep(1)
        except Exception as e:   # never let the follower die silently
            log(f"log follower: {e!r}")
            time.sleep(5)


def main():
    os.umask(0o027)
    for d in (MACHINES, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=follow_access_log, daemon=True).start()
    log(f"lab-portal-worker started (max {MAX_GUESTS} guest workstations)")
    while True:
        reqs = take_requests()
        if reqs:
            try:
                batch(reqs)
            except Exception as e:
                log(f"batch failed: {e!r}")
                for r in reqs:
                    if (m := load(r["user"])) and m["state"] == "building" and "created" not in m["phases"]:
                        mark(r["user"], state="failed", error="internal error in the portal worker")
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
