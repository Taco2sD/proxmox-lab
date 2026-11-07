"""lablib: the lab's shared Python library.

Deployed to mgmt01:/usr/local/lib/lab/lablib.py by roles/runner. Imported by:
  lab        the command-line runner (ansible/roles/runner/files/lab), as root
  worker.py  the portal's dispatcher (ansible/roles/portal/files/), as root
  portal.py  the portal's web side (same directory), as the unprivileged user labportal
and by the repository checks (tools/, tests/), so all of them agree on:

  - where things are, and the lab's settings (ansible/group_vars/all.yml)
  - the catalogue (catalog/) and the inventory: fleet files in git, guest records on
    mgmt01, and the rules both must follow (validate) including the address plan
  - safe file I/O: atomic writes, locked read-modify-write, the append-only audit log
  - operations: one JSON file per thing `lab` does, which the admin page shows
  - a small Proxmox API client

Standard library plus PyYAML (python3-yaml), nothing else to install or keep updated.
"""
import contextlib
import json
import os
import re
import secrets
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

try:                      # Linux only; the checks in tests/ also import this module on CI
    import fcntl
except ImportError:       # pragma: no cover
    fcntl = None

# ---------------------------------------------------------------- where things are
# The deployment checkout: mgmt01's copy of this repository at the release branch
# (`stable`), kept current by `lab reconcile`. Overridable for the checks in tests/.
REPO = Path(os.environ.get("LAB_REPO", "/opt/proxmox-lab"))
# Runtime state on mgmt01. Directory modes are set by roles/runner (tasks/main.yml):
# the web side (group labportal) may read most of it and write only requests/ and
# passwords/; everything else is written by root (lab, worker.py).
STATE = Path(os.environ.get("LAB_STATE", "/var/lib/lab"))
GUESTS = STATE / "guests"            # guests/<host>.json: one record per portal machine
OPS = STATE / "ops"                  # ops/<id>.json: one record per operation
REQUESTS = STATE / "requests"        # the web side's requests to the worker
PASSWORDS = STATE / "passwords"      # passwords/<user>: guest passwords (never in git)
APPROVALS = STATE / "approvals"      # approvals/<host>.json: an admin approved destroying it
TOFU_STATE = STATE / "tofu"          # OpenTofu state: fleet.tfstate, guest-<host>.tfstate
AUDIT = STATE / "audit.jsonl"        # append-only record of every operation step
OBSERVED = STATE / "observed.json"   # what Proxmox reports (worker.py, every minute)
CHECKINS = STATE / "checkins.json"   # last finished configuration run per workstation IP
ACTIVITY = STATE / "activity.json"   # last report of a session (SSH, desktop) per workstation IP
IMAGE = STATE / "image.json"         # the current golden image of each kind (lab image build)
RECONCILE = STATE / "reconcile.json"  # the reconciler's last run, and destroys awaiting approval
PAUSED = STATE / "reconcile.paused"   # exists: the reconciler does nothing (docs/operations.md)
LOGS = Path(os.environ.get("LAB_LOGS", "/var/log/lab"))   # one log per operation
LOCKS = Path(os.environ.get("LAB_LOCKS", "/run/lab"))   # flock files (roles/runner: tmpfiles.d)
# nginx on mgmt01 writes the requests workstations make while they come up (one-time
# password fetches, /lab-events/...) to this log only (roles/lab_web: lab-events-log.conf)
EVENTS_LOG = Path("/var/log/nginx/lab-events.log")
TOFU_ENV = Path("/etc/proxmox-lab/tofu.env")   # Proxmox API token (root only, never in git)

# People (the welcome page, docs/self-service.md). AD is the record of who works here;
# none of it is in git (the repository is public).
PEOPLE = STATE / "people.json"        # AD's staff accounts, exported by worker.py every minute
INVITES = STATE / "invites"           # invites/<user>.json: sign-up link (hash, expiry); <user>.used: spent
MAILBOX = STATE / "mailbox.json"      # the demo mailbox's welcome emails (`lab people seed`)
ONBOARDING = STATE / "onboarding"     # onboarding/<user>.json: how setting up that account went
# Sign-ups carry the new password, so they go through memory only: /run is a tmpfs.
SIGNUPS = LOCKS / "signups"           # signups/<user>.json: web side -> worker, read and deleted at once
KEYS = Path("/var/www/lab/keys")      # keys/<user>: SSH public keys, served to workstations by nginx

# Machines the portal must never touch, whatever a request says. They aren't in the
# workstation inventory, so OpenTofu and the identity cleanup can't reach them anyway;
# this is the second lock on the door.
INFRA = frozenset({"pve01", "dc01", "mgmt01"})
HOST_RE = re.compile(r"^ws[a-z0-9-]{1,13}$")    # NetBIOS limit: 15 characters
USER_RE = re.compile(r"^[a-z][a-z0-9]{1,19}$")   # AD usernames (sAMAccountName: up to 20)
MAC_PREFIX = "BC:24:11:00:00"                    # Proxmox's OUI; the last byte is the slot

# A guest machine's build, as the owner's page shows it. Each step is recorded once,
# by whoever sees it happen: `lab` (identity, created) or worker.py (the rest, from
# nginx's lab-events log).
PHASES = [
    ("queued", "Request received", "The portal queued your request."),
    ("identity", "Identity ready", "AD account, DHCP reservation and one-time join password created."),
    ("created", "VM created", "Cloned from the lab's golden image and started."),
    ("joining", "Joining the domain", "First boot: domain join and role configuration. About 3 minutes."),
    ("ready", "Ready", ""),
]
# Removing a machine, as the admin page shows it. Fleet machines go through git first
# (committed, released = the change passed CI and reached the release branch).
REMOVAL_STEPS = {
    "guest": ["queued", "destroying", "destroyed", "cleaning"],
    "fleet": ["queued", "committed", "released", "destroying", "destroyed", "cleaning"],
}

# ---------------------------------------------------------------- settings and catalogue
_cache = {}


def _yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def settings(repo=None):
    """ansible/group_vars/all.yml: the lab's settings (plain values only; see its header)."""
    repo = Path(repo or REPO)
    key = ("settings", repo)
    if key not in _cache:
        _cache[key] = _yaml(repo / "ansible" / "group_vars" / "all.yml")
    return _cache[key]


def catalog(repo=None):
    """{role: definition} from catalog/*.yml."""
    repo = Path(repo or REPO)
    return {p.stem: _yaml(p) for p in sorted((repo / "catalog").glob("*.yml"))}


def teams(repo=None):
    """{team: definition} from inventory/teams.yml (see its header)."""
    return _yaml(Path(repo or REPO) / "inventory" / "teams.yml")


def fleet(repo=None):
    """{host: spec} from inventory/workstations/*.yml (one file per machine)."""
    repo = Path(repo or REPO)
    found = {}
    for p in sorted((repo / "inventory" / "workstations").glob("*.yml")):
        spec = _yaml(p) or {}
        found[p.stem] = {**spec, "kind": "fleet"}
    return found


def address_for(vmid, cfg=None):
    """The address plan (ansible/group_vars/all.yml): VM 1NN -> 10.10.10.NN, MAC ...:NN."""
    cfg = cfg or settings()
    n = int(vmid) - 100
    prefix = cfg["lab_gateway"].rsplit(".", 1)[0]
    return {"ip": f"{prefix}.{n}", "mac": f"{MAC_PREFIX}:{n:02d}"}


def validate(machines, cat, cfg):
    """Problems with an inventory ({host: spec}), as readable sentences; [] if none.
    Used by tools/validate_inventory.py (CI), by `lab` before every change, and for
    guest records by `lab status`."""
    problems, seen = [], {"vmid": {}, "ip": {}, "mac": {}}
    for host, spec in sorted(machines.items()):
        where = f"{host}:"
        if not HOST_RE.match(host) or host in INFRA:
            problems.append(f"{where} name must be 'ws' plus up to 13 lowercase letters, digits or '-'")
        missing = [k for k in ("vmid", "mac", "ip", "role") if k not in spec]
        if missing:
            problems.append(f"{where} missing {', '.join(missing)}")
            continue
        kind = spec.get("kind", "fleet")
        low, high = cfg["fleet_vmids"] if kind == "fleet" else cfg["guest_vmids"]
        if not isinstance(spec["vmid"], int) or not low <= spec["vmid"] <= high:
            problems.append(f"{where} vmid {spec['vmid']} is outside the {kind} range {low}-{high}")
            continue
        want = address_for(spec["vmid"], cfg)
        if str(spec["ip"]) != want["ip"]:
            problems.append(f"{where} ip {spec['ip']} should be {want['ip']} for vmid {spec['vmid']}")
        if str(spec["mac"]).upper() != want["mac"]:
            problems.append(f"{where} mac {spec['mac']} should be {want['mac']} for vmid {spec['vmid']}")
        if spec["role"] not in cat:
            problems.append(f"{where} role '{spec['role']}' is not in catalog/")
        if kind == "guest" and not USER_RE.fullmatch(str(spec.get("owner", ""))):
            problems.append(f"{where} guest machines need an owner (an AD username)")
        for field in seen:
            value = str(spec[field]).upper()
            if value in seen[field]:
                problems.append(f"{where} {field} {spec[field]} is also used by {seen[field][value]}")
            seen[field][value] = host
    return problems


# ---------------------------------------------------------------- file I/O
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data, mode=0o640):
    """Atomic: readers see the old file or the new one, never half of one."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


@contextlib.contextmanager
def lock(name, shared=False, wait=True):
    """A named lock across processes (flock on /run/lab/<name>.lock). Yields False
    instead of waiting when wait=False and someone else holds it."""
    LOCKS.mkdir(parents=True, exist_ok=True)
    with open(LOCKS / f"{name}.lock", "a") as f:
        flags = (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | (0 if wait else fcntl.LOCK_NB)
        try:
            fcntl.flock(f, flags)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update_json(path, change, default=None, mode=0o640):
    """Read-modify-write under a lock, for files with more than one writer (a guest
    record is updated by `lab` and by worker.py). `change` edits the dict in place;
    returns the new value, or None if the file doesn't exist and there's no default."""
    with lock("records"):
        data = read_json(path, default)
        if data is None:
            return None
        change(data)
        write_json(path, data, mode)
        return data


def audit(event, **fields):
    """Append one line to the audit log: who did what, when, with what outcome."""
    line = json.dumps({"time": round(time.time(), 3), "event": event, **fields}, sort_keys=True)
    with lock("audit"), open(AUDIT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------- guest records
def guest_path(host):
    return GUESTS / f"{host}.json"


def guests():
    """{host: record} for every guest machine the portal knows, in any state."""
    found = {}
    for p in GUESTS.glob("ws*.json"):
        r = read_json(p)
        if r and r.get("host") == p.stem:
            found[p.stem] = r
    return found


def guest_spec(record):
    """The inventory entry a guest record describes (same shape as a fleet file)."""
    return ({k: record[k] for k in ("vmid", "mac", "ip", "role", "owner")}
            | {"kind": "guest", "staff": bool(record.get("staff"))})


def desired(repo=None):
    """Every workstation that should exist now: the fleet plus guest machines that
    aren't being removed and weren't rejected. What identity reconciliation keeps."""
    want = fleet(repo)
    for host, r in guests().items():
        if r.get("state") != "removing" and not r.get("rejected"):
            want[host] = guest_spec(r)
    return want


def guest_phase(host, phase, **fields):
    """Record a build phase (the first time it happens) and/or other fields."""
    def change(r):
        if phase:
            r.setdefault("phases", {}).setdefault(phase, time.time())
        r.update(fields)
    return update_json(guest_path(host), change)


def images():
    """{kind: {vmid, built, op}}: the current golden image of each kind (headless,
    desktop). Before there were two kinds, the file held the one image's record: that
    was the minimal one, so it reads as headless."""
    data = read_json(IMAGE) or {}
    return {"headless": data} if "vmid" in data else data


def admission(role, cat=None, cfg=None, owner=None):
    """Why a new guest machine of this role can't be built now, or None if it can:
    the person's limit for its kind (staff_limits: one desktop, four headless), the
    lab's count cap, and above all memory: every active guest's size.memory_mb plus
    the new one must fit in guest_memory_mb. Checked by the web side before it asks
    and by the worker again before it builds."""
    cat, cfg = cat or catalog(), cfg or settings()
    active = [r for r in guests().values() if not r.get("rejected") and r.get("state") != "removing"]
    if owner:
        kind = cat[role]["kind"]
        mine = [r for r in active if r.get("staff") and r.get("owner") == owner
                and cat.get(r.get("role"), {}).get("kind") == kind]
        if len(mine) >= cfg["staff_limits"][kind]:
            n = cfg["staff_limits"][kind]
            return f"you have {n} {kind} workstation{'s' if n != 1 else ''} already, the most anyone can have"
    if len(active) >= cfg["max_guests"]:
        return f"the lab is full ({cfg['max_guests']} machines)"
    used = sum(cat.get(r.get("role"), {}).get("size", {}).get("memory_mb", 0) for r in active)
    if used + cat[role]["size"]["memory_mb"] > cfg["guest_memory_mb"]:
        free = max(0, cfg["guest_memory_mb"] - used)
        return f"the lab has {free} MB of memory left, and this workstation needs {cat[role]['size']['memory_mb']} MB"
    return None


def free_guest_vmid(cfg, taken):
    low, high = cfg["guest_vmids"]
    return next((v for v in range(low, high + 1) if v not in taken), None)


# ---------------------------------------------------------------- operations
# An operation is one thing `lab` does: build a guest, delete machines, build the image,
# reconcile the fleet. Each has a record in ops/ (what the admin page's Activity shows),
# a full log in /var/log/lab/<id>.log, and lines in the audit log.
ACTIVE = ("queued", "running", "waiting")


def new_op(kind, actor, hosts=(), **params):
    op_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{secrets.token_hex(2)}"
    op = {"id": op_id, "kind": kind, "actor": actor, "hosts": list(hosts), "params": params,
          "state": "queued", "steps": {}, "error": None, "created": time.time(), "finished": None,
          "log": str(LOGS / f"{op_id}.log")}
    write_json(OPS / f"{op_id}.json", op)
    audit("op", op=op_id, kind=kind, actor=actor, hosts=list(hosts), state="queued")
    return op


def load_op(op_id):
    return read_json(OPS / f"{op_id}.json")


def op_update(op_id, step=None, **fields):
    def change(op):
        if step:
            op["steps"].setdefault(step, time.time())
        op.update(fields)
        if fields.get("state") in ("done", "failed"):
            op["finished"] = time.time()
    op = update_json(OPS / f"{op_id}.json", change)
    if op and (step or "state" in fields):
        audit("op", op=op_id, kind=op["kind"], hosts=op["hosts"], step=step,
              state=op["state"], error=op.get("error"))
    return op


def ops(limit=50):
    """The most recent operations, newest first."""
    found = [r for p in OPS.glob("*.json") if (r := read_json(p))]
    return sorted(found, key=lambda o: o["created"], reverse=True)[:limit]


# ---------------------------------------------------------------- approvals (destroys)
def approvals():
    """{host: approval}: fleet machines an admin approved destroying."""
    return {p.stem: read_json(p, {}) for p in APPROVALS.glob("ws*.json")}


def approve(host, by, op_id=None):
    write_json(APPROVALS / f"{host}.json", {"by": by, "op": op_id, "time": time.time()}, mode=0o600)
    audit("approve-destroy", host=host, by=by, op=op_id)


# ---------------------------------------------------------------- people
# The welcome page (portal.py) looks people up by username in PEOPLE, and lets someone
# whose account doesn't exist yet type their details in from their welcome email. These
# functions turn what they typed from memory into what they meant, and say what they
# changed, so the page can show the corrections before anything is created.
# Deterministic fuzzy matching (difflib) against closed lists: with nine teams and their
# aliases that is exact enough, needs no model or API key, and can't invent a team.
PARTICLES = {"van", "de", "der", "den", "het", "ten", "ter", "te", "von", "da", "di", "du", "le", "la", "del", "dos"}
NOISE = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "head", "chief", "associate",
         "team", "department", "dept", "the", "and", "of", "at", "in", "a", "i"}


def _words(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()


def match_team(text, team_defs):
    """The team someone meant ("Animatoin", "sound design", "Senior Cinematic
    Animator") -> team key, or None if nothing is close enough."""
    import difflib
    probe = " ".join(_words(text))
    if not probe:
        return None
    names = {}
    for key, t in team_defs.items():
        for n in [key, t["name"], *t.get("aliases", [])]:
            names[" ".join(_words(n))] = key
    if probe in names:
        return names[probe]
    def best(p, cutoff):
        hit = difflib.get_close_matches(p, names, n=1, cutoff=cutoff)
        return (difflib.SequenceMatcher(None, p, hit[0]).ratio(), names[hit[0]]) if hit else (0, None)
    score, key = best(probe, 0.75)          # the whole phrase first: "tech producer" is Production
    if key:
        return key
    words = [w for w in probe.split() if w not in NOISE and len(w) > 1]
    scored = [best(w, 0.8) for w in words]  # then single words: "cinematic animator" -> cinematic
    scored = [s for s in scored if s[1]]
    return max(scored)[1] if scored else None


def fold(text):
    """ASCII for usernames: Lefèbre -> lefebre."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text) if c.isascii())


def tidy_name(text, surname=False):
    """Spacing and capitals, only where they're plainly wrong: "nick" -> "Nick",
    "VAN DAM" -> "van Dam". Mixed case (MacBride) is left exactly as typed."""
    text = " ".join(str(text).split())
    if not text or (text != text.lower() and text != text.upper()):
        return text
    parts = text.lower().split()
    last = len(parts) - 1
    return " ".join(p if surname and p in PARTICLES and i < last else p[:1].upper() + p[1:]
                    for i, p in enumerate(parts))


def expected_username(given, surname):
    """The studio's pattern: first letter of the first name, then the whole surname
    (particles included), lowercase ASCII: Pim van Dam -> pvandam."""
    first = fold(given).lower()[:1]
    return re.sub(r"[^a-z0-9]", "", first + fold(surname).lower())[:20]


def known_titles(team_defs, people=None):
    """{job title: team}: the titles in inventory/teams.yml, then the ones people in AD
    already have (people(): exported from AD, never in git)."""
    found = {}
    for key, t in team_defs.items():
        for title in t.get("titles", []):
            found.setdefault(title, key)
    for p in (people or {}).values():
        if p.get("title") and p.get("team") in team_defs:
            found.setdefault(p["title"], p["team"])
    return found


def match_title(text, titles):
    """The job title someone meant ("sound desinger") -> the known title as written
    there ("Sound Designer"), or None if nothing is close enough."""
    import difflib
    probe = " ".join(str(text).split()).lower()
    lower = {t.lower(): t for t in titles}
    if not probe:
        return None
    if probe in lower:
        return lower[probe]
    hit = difflib.get_close_matches(probe, lower, n=1, cutoff=0.8)
    return lower[hit[0]] if hit else None


def check_person(form, team_defs, titles=None):
    """A new hire's details as typed -> (cleaned, corrections, problems).
    corrections: [{field, typed, now}] to show; problems: sentences that block.
    titles: known_titles(), to correct the job title against (and take the team from)."""
    clean, corrections, problems = {}, [], []
    def note(field, typed, now):
        clean[field] = now
        if str(typed).strip() != now:
            corrections.append({"field": field, "typed": str(typed).strip(), "now": now})
    note("given", form.get("given", ""), tidy_name(form.get("given", "")))
    note("surname", form.get("surname", ""), tidy_name(form.get("surname", ""), surname=True))
    title = " ".join(str(form.get("title", "")).split())
    known = match_title(title, titles or {})
    note("title", form.get("title", ""), known or (tidy_name(title) if title == title.lower() else title))
    typed_team = str(form.get("team", ""))
    team = match_team(typed_team, team_defs) or (
        ((titles or {}).get(known) or match_team(title, team_defs)) if not typed_team.strip() else None)
    clean["team"] = team
    if team and team_defs[team]["name"] != typed_team.strip():
        corrections.append({"field": "team", "typed": typed_team.strip(), "now": team_defs[team]["name"]})
    user = str(form.get("username", "")).strip().lower()
    clean["username"] = user
    for field, label in (("given", "first name"), ("surname", "surname"), ("title", "job title")):
        if not clean[field]:
            problems.append(f"Fill in your {label}.")
    if not team:
        problems.append("Which team? Pick one from the list." if typed_team.strip() else "Fill in your team.")
    if not USER_RE.fullmatch(user):
        problems.append("A username is 2 to 20 lowercase letters or digits, as in your welcome email.")
    elif clean["given"] and clean["surname"] and user != expected_username(clean["given"], clean["surname"]):
        problems.append(f"That username doesn't fit the name: for {clean['given']} {clean['surname']} "
                        f"it would be '{expected_username(clean['given'], clean['surname'])}'. "
                        "Check both against your welcome email.")
    return clean, corrections, problems


def password_problems(password, user="", names=()):
    """AD's default policy (Samba: complexity on, at least 7 characters), checked here
    too so the page can say what's wrong before anything is sent to the DC."""
    out = []
    if len(password) < 8:
        out.append("at least 8 characters")
    classes = sum(any(f(c) for c in password) for f in (str.islower, str.isupper, str.isdigit,
                                                         lambda c: not c.isalnum()))
    if classes < 3:
        out.append("three of: lowercase, uppercase, digits, symbols")
    low = password.lower()
    if any(len(n) >= 3 and n.lower() in low for n in (user, *names)):
        out.append("not your username or name")
    return out


def people():
    """{username: person} from PEOPLE (worker.py exports it from AD every minute)."""
    return (read_json(PEOPLE) or {}).get("people", {})


def dc_people(command, payload=None):
    """Run /usr/local/sbin/lab-people on dc01 (roles/ad_people) over svc-runner's key,
    JSON in on stdin and out on stdout. Root only (mgmt01's key for svc-runner)."""
    dc01 = settings()["dc01_ip"]
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", f"svc-runner@{dc01}",
                        "sudo", "/usr/local/sbin/lab-people", command],
                       input=json.dumps(payload or {}), capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(r.stdout or "{}")
    except ValueError:
        out = {}
    if r.returncode != 0:
        raise RuntimeError(out.get("error") or r.stderr.strip() or f"lab-people {command} failed")
    return out


def export_people():
    """AD's staff accounts -> PEOPLE, for the web side (which can't reach AD itself)."""
    found = dc_people("export")["people"]
    write_json(PEOPLE, {"time": time.time(), "people": found})
    return found


def staff_host(vmid):
    """A staff member's workstation is called ws<NN> after its VM ID (VM 1NN): a person
    can have several, and every name fits NetBIOS. (Visitors' machines: ws-<username>.)"""
    return f"ws{int(vmid) - 100}"


# ---------------------------------------------------------------- reading tools' output
TOFU_LINE = re.compile(
    r'module\.workstation(?:\["(?P<host>[^"]+)"\])?\.proxmox_virtual_environment_vm\.this: '
    r'(?P<what>Creating|Creation complete|Destroying|Destruction complete)')


def plan_changes(plan):
    """{host: create|replace|update|delete} from `tofu show -json <plan>`."""
    changes = {}
    for rc in plan.get("resource_changes", []):
        if rc.get("type") != "proxmox_virtual_environment_vm":
            continue
        m = re.search(r'module\.workstation(?:\["([^"]+)"\])?', rc.get("address", ""))
        host = (m.group(1) if m and m.group(1) else rc.get("index")) or rc.get("name")
        actions = rc["change"]["actions"]
        if actions == ["no-op"] or actions == ["read"]:
            continue
        kind = ("replace" if "delete" in actions and "create" in actions else
                "create" if actions == ["create"] else
                "delete" if actions == ["delete"] else "update")
        changes[str(host)] = kind
    return changes


def parse_event(line):
    """One line of nginx's lab-events log (JSON, see roles/lab_web) -> dict or None."""
    try:
        e = json.loads(line)
        return {"time": e["time"], "ip": e["ip"], "uri": e["uri"], "status": int(e["status"])}
    except (ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- running things
def run(cmd, log=None, on_line=None, echo=False, **kw):
    """Run a command, streaming its output line by line to a log file (and the
    terminal when echo=True). Returns (exit code, last 20 lines)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1, **kw)
    tail = []
    for line in proc.stdout:
        if log:
            log.write(line)
            log.flush()
        if echo:
            print(line, end="", flush=True)
        tail = (tail + [line.rstrip()])[-20:]
        if on_line:
            on_line(line)
    return proc.wait(), "\n".join(tail)


def read_env(path):
    """KEY=VALUE lines (as in /etc/proxmox-lab/tofu.env) -> dict."""
    env = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')
    return env


class Proxmox:
    """Just enough of the Proxmox VE API for `lab` and worker.py, with the same API
    token OpenTofu uses (terraform@pve, not root; see docs/boundaries.md)."""

    def __init__(self, env_file=TOFU_ENV):
        env = read_env(env_file)
        self.base = env["PROXMOX_VE_ENDPOINT"].rstrip("/") + "/api2/json"
        self.auth = "PVEAPIToken=" + env["PROXMOX_VE_API_TOKEN"]
        self.ctx = ssl.create_default_context()
        if env.get("PROXMOX_VE_INSECURE", "").lower() == "true":
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        self.node = settings()["pve_node"]

    def call(self, method, path, data=None):
        # doseq: a list is a repeated field, as Proxmox takes arrays (agent/exec's command)
        body = urllib.parse.urlencode(data or {}, doseq=True).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, context=self.ctx, timeout=30) as r:
            return json.load(r).get("data")

    def wait(self, upid, timeout=600):
        """Wait for a Proxmox task (the UPID an API call returned) to finish. Some calls
        finish at once and return no task; then there's nothing to wait for."""
        if not upid:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.call("GET", f"/nodes/{self.node}/tasks/{urllib.parse.quote(upid)}/status")
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise RuntimeError(f"Proxmox task failed: {st.get('exitstatus')}")
                return
            time.sleep(2)
        raise TimeoutError(f"Proxmox task still running after {timeout}s: {upid}")

    def vms(self):
        """{vmid: {name, status, power, tags, template}} for every VM on the node.
        power is what people see: running, paused, hibernated (suspended to disk:
        stopped, with its memory saved and the "suspended" lock) or stopped."""
        found = {}
        for v in self.call("GET", f"/nodes/{self.node}/qemu") or []:
            status, lock = v.get("status"), v.get("lock")
            power = ("hibernated" if lock == "suspended" else
                     "paused" if status == "running" and v.get("qmpstatus") == "paused" else status)
            found[int(v["vmid"])] = {"name": v.get("name"), "status": status, "power": power,
                                     "uptime": v.get("uptime", 0),                 # seconds since started
                                     "tags": [t for t in (v.get("tags") or "").split(";") if t],
                                     "template": bool(v.get("template"))}
        return found

    # Power, as Proxmox names it. Hibernate = suspend to disk (VMware's "suspend"): the
    # memory goes to the VM's storage and the VM stops, freeing its RAM; start brings it
    # back exactly where it was. Shutdown asks the guest (ACPI, the guest agent) nicely.
    POWER = {"start": ("start", {}), "shutdown": ("shutdown", {"timeout": "120"}),
             "reboot": ("reboot", {}), "hibernate": ("suspend", {"todisk": "1"})}

    def run_in_guest(self, vmid, command):
        """Start a command inside a running VM through the QEMU guest agent (the token's
        VM.GuestAgent.Unrestricted). Not waited for: returns the guest's process id."""
        return self.call("POST", f"/nodes/{self.node}/qemu/{int(vmid)}/agent/exec", {"command": list(command)})

    def power(self, vmid, action, wait=True):
        what, data = self.POWER[action]
        upid = self.call("POST", f"/nodes/{self.node}/qemu/{int(vmid)}/status/{what}", data)
        if wait:
            self.wait(upid, timeout=300)
        return upid
