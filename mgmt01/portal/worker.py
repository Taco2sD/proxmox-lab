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
STALL = 20 * 60   # seconds without a new phase before a build counts as failed
DC =["ssh", "-n", "-o", "BatchMode=yes", "jrhodes@10.10.10.5"]   # the runner key from `lab`
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


def install_started(user):
    with lock:
        m = load(user)
        if not m:
            return
        for later in ("installing", "installed", "ready"):
            m["phases"].pop(later, None)
        m["phases"]["installing"] = time.time()
        m.update(state="building", error=None)
        save(m)
    log(f"{m['host']}: installing")


def removal_step(user, step):
    """Record a step of a removal (queued, recorded, destroying, destroyed, cleaning)
    the first time it happens; the admin page shows them as progress."""
    with lock:
        m = load(user)
        if not m:
            return
        steps = m.setdefault("removal", {})
        if step not in steps:
            steps[step] = time.time()
            save(m)
            log(f"{m['host']}: removal {step}")


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
    """Waiting requests and their files. The files are deleted only once each request
    has a machine file (see batch): the web side finds a request in one or the other,
    and a visitor's page never lands in the gap between them ("Not found")."""
    reqs = []
    for path in sorted(REQUESTS.glob("*.json")):
        try:
            reqs.append((path, json.loads(path.read_text())))
        except (OSError, ValueError):
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
    deleted_by = {}

    for _, req in reqs:
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
            # The owner proves it with their token; a lab admin (checked against AD's
            # ws-admins by the web side) may delete any guest machine, in any state.
            admin = req.get("admin")
            if not m or (not admin and m.get("token_sha256") != req.get("token_sha256")):
                continue
            deleted_by[user] = f"admin {admin}" if admin else "owner"
            if never_built(m):                              # rejected: nothing in git or AD
                (MACHINES / f"{user}.json").unlink(missing_ok=True)
                (PASSWORDS / user).unlink(missing_ok=True)
                continue
            (GUESTS / f"{m['host']}.yml").unlink(missing_ok=True)
            # Removal progress is its own timeline (a retry starts it afresh)
            mark(user, state="removing", error=None, removal={"queued": req["time"]})
            removes.append(user)

    for path, _ in reqs:          # every request now has a machine file (or was dropped)
        path.unlink(missing_ok=True)
    if not creates and not removes:
        return
    parts = [f"add ws-{u} ({load(u)['role']}, owner {u})" for u in creates] + \
            [f"remove ws-{u} (by {deleted_by[u]})" for u in removes]
    git("add", "-A", "inventory/guests")
    # Nothing to commit happens when retrying a removal whose file is already gone
    # from git; the clean-up below still runs.
    if git("diff", "--cached", "--quiet").returncode == 0:
        result = subprocess.CompletedProcess([], 0, "", "")
    else:
        result = git("commit", "-q", "-m", "Portal: " + "; ".join(parts))
        if result.returncode == 0:
            result = git("push", "-q", "origin", "HEAD:main")
    if result.returncode != 0:
        why = "could not commit the request to git"
        log(f"{why}: {result.stdout}{result.stderr}")
        for u in creates + removes:
            mark(u, state="failed", error=why)
        return
    for u in creates:
        mark(u, "recorded")
    for u in removes:
        removal_step(u, "recorded")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    host_of = {f"ws-{u}": u for u in creates}
    removing = {f"ws-{u}": u for u in removes}

    def follow(line):   # OpenTofu's progress lines name each VM
        m = re.search(r'workstation\["(ws-[a-z0-9]+)"\]: (Creating|Creation complete|Destroying|Destruction complete)', line)
        if not m:
            return
        host, what = m.groups()
        if host in host_of:
            # infra.yml and otp.yml run before OpenTofu, so identity is done once it starts
            mark(host_of[host], "identity")
            if what == "Creation complete":
                mark(host_of[host], "created")
        elif host in removing:
            removal_step(removing[host], "destroying" if what == "Destroying" else "destroyed")

    env = {**os.environ, "LAB_YES": "1"}
    with open(LOGS / f"{stamp}-apply.log", "w") as f:
        rc, tail = run(["lab", "apply"], f, follow, env=env)
    if rc != 0:
        for u in creates:
            if "created" not in (load(u) or {}).get("phases", {}):
                mark(u, state="failed", error=f"lab apply failed (log {stamp}-apply.log)")
        log(f"lab apply failed:\n{tail}")

    if removes and rc != 0:
        # The VM may still exist: don't delete its accounts and records under it.
        # The machine stays listed as failed, so an admin can retry the delete.
        for u in removes:
            mark(u, state="failed", error=f"removing the VM failed (log {stamp}-apply.log)")
    elif removes:
        # AD user + computer account, autoinstall record, DHCP lease and with it the
        # A/PTR records (dhcp_server role), then the portal's own files
        for u in removes:
            removal_step(u, "destroyed")      # a retry: the VM was already gone
            removal_step(u, "cleaning")
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


POSITION = STATE / "access-log.position"


def read_position():
    try:
        inode, pos = POSITION.read_text().split()
        return int(inode), int(pos)
    except (OSError, ValueError):
        return None


def save_position(inode, pos):
    if read_position() != (inode, pos):
        POSITION.write_text(f"{inode} {pos}\n")


def follow_access_log():
    """tail -F that survives restarts: the position read so far is saved in POSITION,
    so a worker restart (a deployment, say) doesn't miss a guest's progress."""
    f, inode, first = None, None, True
    while True:
        try:
            st = ACCESS_LOG.stat()
            if f is None or st.st_ino != inode:
                if f:
                    f.close()
                f, inode = open(ACCESS_LOG), st.st_ino
                if first:
                    first = False
                    saved = read_position()
                    if saved and saved[0] == inode and saved[1] <= st.st_size:
                        f.seek(saved[1])         # same file as before the restart: continue
                    elif not saved:
                        f.seek(0, os.SEEK_END)   # very first start: history isn't ours
                    # otherwise logrotate replaced the file meanwhile: read it all
            line = f.readline()
            if not line:
                save_position(inode, f.tell())
                time.sleep(1)
                continue
            m = LINE.match(line)
            if not m:
                continue
            ip, path, ok = m.group(1), m.group(2), m.group(3) in ("200", "204")
            for mach in all_machines():
                if mach.get("ip") != ip or "recorded" not in mach["phases"]:
                    continue
                user, state = mach["user"], mach["state"]
                if path.endswith("/user-data") and ok:
                    # the installer fetches this exactly once per install, so it means a
                    # (re)install starts now, e.g. an admin reimaging a failed machine
                    install_started(user)
                elif state != "building":
                    continue
                elif path.endswith("/otp") and ok:
                    mark(user, "installed")
                elif path.endswith("/otp"):
                    # the installer stops at "An error occurred" when it can't get this
                    mark(user, state="failed", error=f"the installer could not fetch its one-time join password (HTTP {m.group(3)})")
                elif path == "/lab-events/configured" and ok:
                    mark(user, "ready", state="ready")
        except FileNotFoundError:
            time.sleep(1)
        except Exception as e:   # never let the follower die silently
            log(f"log follower: {e!r}")
            time.sleep(5)


def fail_stalled():
    """A build with no new phase for STALL seconds has stopped somewhere (the installer
    waits at an error prompt forever). Say so instead of showing progress that isn't."""
    for m in all_machines():
        if m["state"] == "building" and "recorded" in m["phases"]:
            phase, since = max(m["phases"].items(), key=lambda kv: kv[1])
            if time.time() - since > STALL:
                mark(m["user"], state="failed", error=f"no progress for {STALL // 60} minutes after '{phase}'")


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
                for _, r in reqs:
                    if (m := load(r["user"])) and m["state"] == "building" and "created" not in m["phases"]:
                        mark(r["user"], state="failed", error="internal error in the portal worker")
        fail_stalled()
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
