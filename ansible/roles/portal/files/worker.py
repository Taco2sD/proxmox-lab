#!/usr/bin/env python3
"""Self-service portal, worker side: the dispatcher. Runs on mgmt01 as root.

Deployed to mgmt01:/usr/local/lib/lab-portal/worker.py by roles/portal, run by
lab-portal-worker.service. docs/self-service.md describes the whole flow.

The web side (portal.py, unprivileged) can only drop request files. This process turns
them into operations, and `lab` carries them out:

  requests/<...>.json  ->  checks, a guest record / an approval  ->  ops/<id>.json
                       ->  `systemd-run --unit lab-op-<id> lab op run <id>`

Each operation runs in its own transient systemd unit, not as a child of this process,
so restarting the worker (a deployment does that) never kills a build or a delete in
progress, and `journalctl -u lab-op-<id>` shows its output.

Sign-ups from the welcome page take a different path, because they carry a new
password: the web side writes them to /run/lab/signups (a tmpfs, so never to disk),
and this process reads and deletes each one at once, sets up the account on dc01
(lablib.dc_people: the password goes over stdin) and then builds the first workstation
like any other staff machine.

Besides dispatching, it watches:
  - nginx's lab-events log: workstations fetching their one-time join password
    (joining) and reporting finished configuration runs (ready, check-ins)
  - Proxmox, every minute: which VMs exist and run (observed.json, for the admin page)
  - stalled builds, and operations whose unit died without finishing
"""
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/usr/local/lib/lab")
import lablib as L  # noqa: E402

STALL = 20 * 60          # a guest build with no new phase for this long has failed
OBSERVE_EVERY = 60       # seconds between Proxmox status reads
DC01 = ["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- starting operations
def launch(op):
    """Run `lab op run <id>` in its own transient systemd unit (see the module docstring)."""
    unit = f"lab-op-{op['id']}"
    r = subprocess.run(["systemd-run", f"--unit={unit}", "--collect", "--quiet",
                        "--property=SyslogIdentifier=lab-op", "/usr/local/bin/lab", "op", "run", op["id"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        L.op_update(op["id"], state="failed", error=f"couldn't start: {r.stderr.strip()}")
    else:
        L.op_update(op["id"], unit=unit)   # reap_ops() checks on it
    log(f"started {unit} ({op['kind']} {' '.join(op['hosts'])})")


def ad_user_exists(user):
    """Guest owners get an AD account; the name must not belong to someone else."""
    dc01 = L.settings()["dc01_ip"]
    r = subprocess.run(DC01 + [f"svc-runner@{dc01}", f"sudo samba-tool user show {user}"], capture_output=True)
    return r.returncode == 0


# ---------------------------------------------------------------- requests from the web side
def take_requests():
    found = []
    for path in sorted(L.REQUESTS.glob("*.json")):
        req = L.read_json(path)
        if req is None:
            path.unlink(missing_ok=True)
        else:
            found.append((path, req))
    return found


def reject(req, why):
    """A create request that can't be fulfilled: the owner's page shows why. Nothing
    was created anywhere, so the record says so (rejected) and needs no clean-up."""
    host = f"ws-{req['user']}"
    log(f"rejected {host}: {why}")
    L.write_json(L.guest_path(host), {
        "host": host, "owner": req["user"], "role": req["role"], "vmid": None, "ip": "", "mac": "",
        "token_sha256": req["token_sha256"], "state": "failed", "error": why, "rejected": True,
        "phases": {"queued": req["time"]}})
    (L.PASSWORDS / req["user"]).unlink(missing_ok=True)


def create(req):
    cfg, host = L.settings(), f"ws-{req['user']}"
    existing = L.guests()
    if host in existing and not existing[host].get("rejected"):
        return                                         # already handled
    if ad_user_exists(req["user"]):
        return reject(req, f"an account called '{req['user']}' already exists in AD")
    active = [r for r in existing.values() if not r.get("rejected")]
    vmid = L.free_guest_vmid(cfg, {r["vmid"] for r in active})
    if (why := L.admission(req["role"], cfg=cfg)) or vmid is None:
        return reject(req, why or "the lab is full")
    L.write_json(L.guest_path(host), {
        "host": host, "owner": req["user"], "role": req["role"], "vmid": vmid,
        **L.address_for(vmid, cfg), "token_sha256": req["token_sha256"], "state": "building",
        "error": None, "phases": {"queued": req["time"]}})
    launch(L.new_op("guest-create", f"visitor {req['user']}", [host]))


def delete_guest(host, actor):
    r = L.read_json(L.guest_path(host))
    if not r:
        return
    if r.get("rejected"):                              # nothing was ever built
        L.guest_path(host).unlink(missing_ok=True)
        return
    L.update_json(L.guest_path(host), lambda x: x.update(
        state="removing", error=None, removal={"queued": time.time()}))
    launch(L.new_op("guest-delete", actor, [host]))


# ---------------------------------------------------------------- staff (the welcome page)
def onboarding(user, **fields):
    """What the welcome page shows about a person's sign-up and their last request."""
    L.update_json(L.ONBOARDING / f"{user}.json", lambda r: r.update(fields, time=time.time()), default={})


def staff_create(user, role, queued):
    """Another workstation for a staff member (their first comes with the sign-up)."""
    cfg, existing = L.settings(), L.guests()
    active = [r for r in existing.values() if not r.get("rejected")]
    vmid = L.free_guest_vmid(cfg, {r["vmid"] for r in active})
    if (why := L.admission(role, cfg=cfg, owner=user)) or vmid is None:
        return onboarding(user, error=why or "the lab is full right now; try again later")
    host = L.staff_host(vmid)
    L.write_json(L.guest_path(host), {
        "host": host, "owner": user, "role": role, "vmid": vmid, "staff": True, **L.address_for(vmid, cfg),
        "state": "building", "error": None, "phases": {"queued": queued}})
    onboarding(user, error=None)
    launch(L.new_op("guest-create", f"staff {user}", [host]))


# ---------------------------------------------------------------- power (My lab, idle machines)
def power(host, action, actor):
    """Start, shut down, restart or hibernate a guest machine, in the background (a
    hibernation writes the machine's memory to disk: tens of seconds). The record says
    what's under way, so My lab can show it; Proxmox's answer lands in observed.json."""
    r = L.read_json(L.guest_path(host)) or {}
    if not r.get("vmid") or r.get("state") != "ready" or r.get("power_action"):
        return
    L.guest_phase(host, None, power_action={"action": action, "time": time.time(), "by": actor}, power_error=None)
    L.audit("power", host=host, action=action, by=actor)

    def run():
        error = None
        try:
            L.Proxmox().power(r["vmid"], action)
        except Exception as e:                      # noqa: BLE001
            error = f"{action} failed: {e}"
            log(f"{host}: {error}")
        extra = {"resumed": time.time()} if action == "start" and not error else {}
        L.guest_phase(host, None, power_action=None, power_error=error, **extra)
        observe_vms()
        log(f"{host}: {action} by {actor}: {'failed' if error else 'done'}")
    threading.Thread(target=run, daemon=True).start()


def configure(hosts, actor):
    """Start a configuration run on each machine now rather than at its next timer
    (roles/base: ansible-pull.service, every pull_interval), through the guest agent.
    Only starts it: the machine reports back as after any run (local.yml: lab-events
    /configured), which the admin page shows as Last activity."""
    vmids = {h: s["vmid"] for h, s in L.fleet().items()} | {h: r.get("vmid") for h, r in L.guests().items()}

    def run():
        px = L.Proxmox()
        for host in hosts:
            if host in L.INFRA or not vmids.get(host):
                log(f"refused to configure {host}: not a workstation")
                continue
            try:
                px.run_in_guest(vmids[host], ["systemctl", "start", "--no-block", "ansible-pull.service"])
            except Exception as e:                  # noqa: BLE001
                log(f"{host}: couldn't start a configuration run: {e}")
                continue
            L.audit("configure", host=host, by=actor)
            log(f"{host}: configuration run started by {actor}")
    threading.Thread(target=run, daemon=True).start()


def hibernate_idle():
    """Staff machines nobody has had a session on for idle_hibernate_minutes go to
    sleep (hibernate: suspended to disk, so they resume exactly where they were and
    free their memory meanwhile). Sessions are reported by the machines themselves
    (roles/base: lab-activity, every five minutes while someone is logged in)."""
    cfg = L.settings()
    limit = cfg["idle_hibernate_minutes"] * 60
    observed = L.read_json(L.OBSERVED) or {}
    vms = observed.get("vms", {})
    activity = L.read_json(L.ACTIVITY) or {}
    for host, r in L.guests().items():
        vm = vms.get(str(r.get("vmid")))
        if not r.get("staff") or r.get("state") != "ready" or not vm or vm.get("power") != "running":
            continue
        # started (or woken) outside My lab, e.g. in the Proxmox UI: active since then
        started = observed.get("time", 0) - vm.get("uptime", 0)
        last = max(activity.get(r["ip"], 0), r.get("phases", {}).get("ready", 0), r.get("resumed", 0), started)
        if time.time() - last > limit:
            power(host, "hibernate", f"idle for {cfg['idle_hibernate_minutes'] / 60:g} hours")


def take_signups():
    """Read and delete at once: the files hold a new password (see the module docstring)."""
    found = []
    for path in sorted(L.SIGNUPS.glob("*.json")):
        try:
            found.append(L.read_json(path))
        finally:
            path.unlink(missing_ok=True)
    return [s for s in found if s]


def signup(s):
    user = s["user"]
    onboarding(user, state="account", error=None, started=s["time"])
    try:
        L.dc_people("claim", {"username": user, "password": s["password"], "person": s.get("person"),
                              "teams": L.teams()})
    except Exception as e:                         # noqa: BLE001  Samba's message, never the request
        log(f"sign-up {user}: {e}")
        return onboarding(user, state="failed", error=str(e))
    log(f"sign-up {user}: account ready ({'created' if s.get('person') else 'claimed'})")
    if s.get("pubkey"):
        set_key(user, s["pubkey"])
    try:
        L.export_people()
    except Exception as e:                         # noqa: BLE001
        log(f"people export: {e!r}")
    onboarding(user, state="ready")
    staff_create(user, s["role"], s["time"])


def set_key(user, pubkey):
    """A person's SSH public key, or none. Public, so world-readable: nginx serves it to
    the workstations (roles/lab_web: lab-keys.conf), whose sshd asks for it on every key
    login (roles/ad_join), so a new or replaced key works on all their machines at once."""
    path = L.KEYS / user
    if not pubkey:
        path.unlink(missing_ok=True)
        return log(f"{user}: SSH key removed")
    L.KEYS.mkdir(parents=True, exist_ok=True)
    path.write_text(pubkey.strip() + "\n", encoding="utf-8")
    os.chmod(path, 0o644)
    return log(f"{user}: SSH key set")


def handle(req):
    action = req.get("action")
    if action == "create":
        create(req)
    elif action == "staff-create":                       # a signed-in staff member (checked by the web side)
        staff_create(req["user"], req["role"], req["time"])
    elif action == "staff-power":                        # the owner (checked by the web side, and here)
        r = L.read_json(L.guest_path(req.get("host", ""))) or {}
        if r.get("staff") and r.get("owner") == req.get("user") and req.get("op") in L.Proxmox.POWER:
            power(r["host"], req["op"], f"staff {req['user']}")
    elif action == "staff-key" and L.USER_RE.fullmatch(req.get("user", "")):
        set_key(req["user"], req.get("pubkey", ""))
    elif action == "staff-delete":
        r = L.read_json(L.guest_path(req.get("host", ""))) or {}
        if r.get("staff") and r.get("owner") == req.get("user"):
            delete_guest(r["host"], f"staff {req['user']}")
    elif action == "delete" and "token_sha256" in req:   # the owner, proven by their token
        host = f"ws-{req['user']}"
        r = L.read_json(L.guest_path(host)) or {}
        if r.get("token_sha256") == req["token_sha256"]:
            delete_guest(host, f"owner {req['user']}")
    elif action == "delete" and req.get("admin"):        # an admin (AD ws-admins, checked by the web side)
        actor = f"admin {req['admin']}"
        fleet = L.fleet()
        guests = L.guests()
        for host in req.get("hosts", []):
            if host in L.INFRA:
                log(f"refused to delete {host}: not a workstation")
            elif host in guests:
                delete_guest(host, actor)
        doomed = [h for h in req.get("hosts", []) if h in fleet and h not in L.INFRA]
        if doomed:
            launch(L.new_op("fleet-delete", actor, doomed))
    elif action == "configure" and req.get("admin"):     # an admin: a configuration run now
        configure(req.get("hosts", []), f"admin {req['admin']}")
    elif action == "approve" and req.get("admin"):       # approve destroys the reconciler found
        for host in req.get("hosts", []):
            if host not in L.INFRA:
                L.approve(host, f"admin {req['admin']}")


# ---------------------------------------------------------------- what workstations report
def follow_events():
    """tail -F of nginx's lab-events log (JSON lines), surviving restarts: the position
    read so far is saved, so a worker restart doesn't miss a machine's progress."""
    pos_file = L.STATE / "events-log.position"
    f, inode, first = None, None, True
    while True:
        try:
            st = L.EVENTS_LOG.stat()
            if f is None or st.st_ino != inode:
                if f:
                    f.close()
                f, inode = open(L.EVENTS_LOG, encoding="utf-8"), st.st_ino  # noqa: SIM115 (kept open: tail -F)
                saved = L.read_json(pos_file) if first else None
                if first and saved and saved.get("inode") == inode and saved.get("pos", 0) <= st.st_size:
                    f.seek(saved["pos"])            # same file as before the restart: continue
                elif first and not saved:
                    f.seek(0, os.SEEK_END)          # very first start: history isn't ours
                first = False                       # (otherwise: rotated meanwhile, read it all)
            line = f.readline()
            if not line:
                L.write_json(pos_file, {"inode": inode, "pos": f.tell()})
                time.sleep(1)
                continue
            event = L.parse_event(line)
            if event:
                on_event(event)
        except FileNotFoundError:
            time.sleep(2)
        except Exception as e:                      # noqa: BLE001  never let the follower die
            log(f"event follower: {e!r}")
            time.sleep(5)


def on_event(e):
    ip, uri, ok = e["ip"], e["uri"], e["status"] in (200, 204)
    if uri == "/lab-events/configured" and ok:
        L.update_json(L.CHECKINS, lambda c: c.update({ip: time.time()}), default={})
    if uri == "/lab-events/active" and ok:          # someone has a session (roles/base: lab-activity)
        L.update_json(L.ACTIVITY, lambda c: c.update({ip: time.time()}), default={})
    for host, r in L.guests().items():
        # (The clone can fetch its password before OpenTofu reports "created", so only
        # require that its identity exists.)
        if r.get("ip") != ip or r.get("state") != "building" or "identity" not in r.get("phases", {}):
            continue
        if re.fullmatch(r"/otp/[^/]+", uri):
            if ok:
                L.guest_phase(host, "joining")
            else:   # the machine can't join without it; say so instead of waiting
                L.guest_phase(host, None, state="failed",
                              error=f"the machine could not fetch its one-time join password (HTTP {e['status']})")
        elif uri == "/lab-events/configured" and ok:
            L.guest_phase(host, "ready", state="ready")
            threading.Thread(target=observe_vms, daemon=True).start()   # My lab shows it running now


# ---------------------------------------------------------------- periodic checks
def observe_vms():
    try:
        L.write_json(L.OBSERVED, {"time": time.time(), "vms": {str(k): v for k, v in L.Proxmox().vms().items()}})
    except Exception as e:                              # noqa: BLE001
        log(f"observe: {e!r}")


def observe():
    """What Proxmox has (status and power, for the admin page and My lab; fleet
    machines have no build record), and who AD has, for the welcome page's lookups."""
    observe_vms()
    try:
        L.export_people()
    except Exception as e:                              # noqa: BLE001
        log(f"people export: {e!r}")


def fail_stalled():
    """A build with no new phase for STALL seconds has stopped somewhere. Say so."""
    for host, r in L.guests().items():
        if r.get("state") == "building" and r.get("phases"):
            phase, since = max(r["phases"].items(), key=lambda kv: kv[1])
            if time.time() - since > STALL:
                L.guest_phase(host, None, state="failed", error=f"no progress for {STALL // 60} minutes after '{phase}'")


def reap_ops():
    """An operation still marked running whose process is gone died without finishing
    (crash, reboot, stopped by hand): mark it failed so nothing waits on it forever, and
    the admin page's Activity doesn't say "In progress" forever. Operations this worker
    started have a systemd unit; `lab` run in a terminal records its process id."""
    for op in L.ops(100):
        unit, pid = op.get("unit"), op.get("pid")
        if op["state"] != "running" or not (unit or pid):
            continue
        if unit:
            active = subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0
        else:
            try:
                active = b"lab" in Path(f"/proc/{int(pid)}/cmdline").read_bytes()
            except OSError:
                active = False
        if not active and time.time() - op["created"] > 30:
            L.op_update(op["id"], state="failed", error="the operation stopped unexpectedly (see its log)")
            for host in op["hosts"]:
                r = L.read_json(L.guest_path(host))
                if r and r.get("state") in ("building", "removing"):
                    L.guest_phase(host, None, state="failed", error="the operation stopped unexpectedly")


def main():
    os.umask(0o027)
    for d in (L.GUESTS, L.OPS, L.LOGS, L.ONBOARDING):
        d.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=follow_events, daemon=True).start()
    log("lab-portal-worker started")
    last_observe = 0
    while True:
        for s in take_signups():
            try:
                signup(s)
            except Exception as e:                       # noqa: BLE001  (no request in the log: it has a password)
                log(f"sign-up {s.get('user')} failed: {type(e).__name__}")
        for path, req in take_requests():
            try:
                handle(req)
            except Exception as e:                       # noqa: BLE001
                log(f"request {path.name} failed: {e!r}")
            path.unlink(missing_ok=True)
        if time.time() - last_observe > OBSERVE_EVERY:
            observe()
            hibernate_idle()
            last_observe = time.time()
        fail_stalled()
        reap_ops()
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
