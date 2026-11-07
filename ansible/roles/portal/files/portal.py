#!/usr/bin/env python3
"""Self-service portal, web side. Runs on mgmt01 as the unprivileged user labportal.

Deployed to mgmt01:/usr/local/lib/lab-portal/portal.py by roles/portal, run by
lab-portal.service, reached through nginx (roles/lab_web: lab-portal-locations.conf).
docs/self-service.md describes the whole flow.

It never touches git, OpenTofu, Proxmox or AD itself (besides checking a password by
binding to AD over LDAPS). It can only
  - reserve a username (by creating its password file, which fails if it exists),
  - spend a sign-up link (by creating its .used file, which fails if it exists),
  - drop a request file into /var/lib/lab/requests/ for the worker (worker.py, root),
    or a sign-up, which carries a password, into /run/lab/signups/ (memory only),
  - read state: guest records, operations, what Proxmox reports, AD's people (via lablib).

Pages:
  /         visitors: one tile per machine, build progress, Connect
  /welcome  the studio's people: look yourself up by username, sign up (set your
            password, optionally an SSH key) and watch your first workstation being built
  /my       "My lab", their portal into the lab: workstations with specs and software,
            consoles, more machines, their SSH key
  /mail     the demo mailbox: the welcome emails `lab people seed` wrote
  /admin    lab admins, signed in with an AD account in ws-admins: every workstation,
            multi-select delete, destroy approvals, Activity
Shared look and helpers: common.css, common.js.

Visitors have no accounts. Each machine has a random secret token; the browser keeps
it in localStorage and sends it in a header (X-Lab-Token), never in a URL, so it never
appears in a log. Only a hash of it is stored.

Standard library plus lablib (PyYAML), python3-ldap3 (admin sign-in) and
python3-cryptography (Guacamole logins).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, "/usr/local/lib/lab")
import lablib as L  # noqa: E402

HERE = Path(__file__).parent
LISTEN = ("127.0.0.1", 8090)
# 3-12 characters: the machine is called ws-<username>, and AD computer names (NetBIOS)
# can't be longer than 15. The worker also refuses names that already exist in AD.
USERNAME = re.compile(r"^[a-z][a-z0-9]{2,11}$")
RESERVED = {"admin", "administrator", "guest", "krbtgt", "root", "labadmin", "ubuntu", "daemon",
            "nobody", "sync", "games", "test", "user", "ansible", "svc"}


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def request(data):
    """Hand something to the worker: one file per request, written atomically."""
    L.write_json(L.REQUESTS / f"{time.time_ns()}-{secrets.token_hex(3)}.json", {**data, "time": time.time()})


# ---------------------------------------------------------------- visitors' machines
def find(token):
    """The guest record behind a token, or a request the worker hasn't picked up yet."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return None
    digest = sha256(token)
    for r in L.guests().values():
        if r.get("token_sha256") == digest:
            return r
    for p in L.REQUESTS.glob("*.json"):
        q = L.read_json(p)
        if q and q.get("token_sha256") == digest and q.get("action") == "create":
            return {"owner": q["user"], "role": q["role"], "host": f"ws-{q['user']}", "ip": "",
                    "state": "building", "error": None, "phases": {"queued": q["time"]}}
    return None


def in_use():
    """Guest machines that exist or are being built, plus requests not picked up yet."""
    hosts = {h for h, r in L.guests().items() if not r.get("rejected")}
    hosts |= {f"ws-{q.get('user')}" for p in L.REQUESTS.glob("*.json")
              if (q := L.read_json(p)) and q.get("action") == "create"}
    return len(hosts)


def username_problem(user):
    if not USERNAME.fullmatch(user):
        return "Use 3 to 12 lowercase letters or digits, starting with a letter."
    if user in RESERVED:
        return f"'{user}' is reserved."
    if (L.PASSWORDS / user).exists():
        return f"'{user}' is already taken."
    return None


def new_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        # AD's complexity rule: at least three character classes
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def public_view(r):
    """What the owner's browser gets: no token hash; the password only once it's ready."""
    view = {k: r.get(k) for k in ("role", "host", "ip", "state", "error", "phases")}
    view["user"] = r.get("owner")
    if r.get("state") == "ready":
        try:
            view["password"] = (L.PASSWORDS / r["owner"]).read_text()
        except OSError:
            view["password"] = None
    return view


# ---------------------------------------------------------------- the browser terminal
JSON_KEY = Path("/etc/lab-portal/json-secret-key")   # shared with Guacamole (roles/guacamole)


CONSOLE_TOKEN = Path("/etc/lab-portal/console-token")   # VM.Console only (roles/pve_console)


def console_ticket(r):
    """A one-time VNC ticket for the machine's own screen, from Proxmox (vncproxy with
    generate-password: an 8-character password for standard VNC clients). Proxmox
    listens for it on pve01 for a few seconds; Guacamole connects within one or two."""
    import ssl
    import urllib.request
    cfg = L.settings()
    req = urllib.request.Request(
        f"https://{cfg['pve_fqdn']}:8006/api2/json/nodes/{cfg['pve_node']}/qemu/{int(r['vmid'])}/vncproxy",
        data=b"generate-password=1", method="POST",
        headers={"Authorization": CONSOLE_TOKEN.read_text().strip()})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10) as resp:
        t = json.load(resp)["data"]
    return {"hostname": cfg["pve01_ip"], "port": str(t["port"]), "password": t["password"]}


def guacamole_login(r, with_password=True, console=None):
    """A Guacamole JSON-auth login for one connection to the owner's machine, valid for
    60 seconds: SSH (the terminal), or with `console` (console_ticket()), the machine's
    own screen over VNC: the Ubuntu login, where the owner signs in with their AD
    password, then their GNOME desktop (roles/desktop). Visitors' passwords are on
    mgmt01 and go into the terminal; staff members' aren't stored anywhere, so the
    terminal or the login screen asks (with_password=False). Returns (name, data).
    Same steps as Guacamole's reference encrypt-json.sh:
    HMAC-SHA256 the JSON with the key, prepend the signature, AES-128-CBC with a zero
    IV (PKCS#7 padding), base64."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes.fromhex(JSON_KEY.read_text().strip())
    if console:
        name, protocol, params = f"{r['host']} desktop", "vnc", dict(console)
        # guacd 1.6.0 drops the connection when the guest changes resolution (and the
        # one-time ticket rules out its automatic reconnect). Without size negotiation it
        # survives; desktops start at 1920x1080 (roles/desktop: monitors.xml), and after a
        # resolution change, Desktop again shows the new size.
        params["disable-display-resize"] = "true"
    else:
        name, protocol = r["host"], "ssh"
        params = {"hostname": r["ip"], "port": "22", "username": r["owner"],
                  "color-scheme": "gray-black", "font-size": "11"}
        if with_password:
            params["password"] = (L.PASSWORDS / r["owner"]).read_text()
    payload = json.dumps({
        "username": r["owner"],
        "expires": int((time.time() + 60) * 1000),                       # milliseconds
        "connections": {name: {"protocol": protocol, "parameters": params}},
    }).encode()
    signed = hmac.new(key, payload, hashlib.sha256).digest() + payload
    padder = padding.PKCS7(128).padder()
    padded = padder.update(signed) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return name, base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def guacamole_url(name, data):
    """Straight to the connection's own page. Guacamole's home page only jumps into a
    lone connection on a fresh login; with a session already open it shows "No recent
    connections". The id is Guacamole's client identifier: base64 of
    "<connection>\0c\0<data source>"."""
    client = base64.b64encode(f"{name}\0c\0json".encode()).decode()
    return f"/guacamole/#/client/{client}?data=" + quote(data, safe="")


# ---------------------------------------------------------------- lab admins (/admin)
# Admins sign in with their AD account; only members of ws-admins (nested membership
# counts) get in. The password is checked by binding to dc01 over LDAPS (Let's Encrypt
# certificate for dc01.lab.radicallydecent.com, verified with the system trust store)
# and is never stored. A signed cookie then carries the session.
SESSION_KEY = Path("/etc/lab-portal/session-key")
SESSION_SECONDS = 8 * 3600
COOKIE = "lab_admin"
# "Not signed in" is 403, never 401: a 401 from behind the VPS's sign-in gate
# (oauth2-proxy, auth_request) would be taken as the gate's own answer.


def ad_admin_login(username, password):
    """True if the AD password is right and the account is in ws-admins."""
    cfg = L.settings()
    return ad_login(username, password, f"CN={cfg['ad_admin_groups'][0]},OU=Groups,OU=Lab,{cfg['ad_base_dn']}")


def ad_login(username, password, group=None):
    """True if the AD password is right (and, with `group`, the account is in it)."""
    import ssl
    from ldap3 import Connection, Server, Tls                          # python3-ldap3
    from ldap3.utils.conv import escape_filter_chars
    cfg = L.settings()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username) or not password:
        return False
    tls = Tls(ca_certs_file="/etc/ssl/certs/ca-certificates.crt", validate=ssl.CERT_REQUIRED)
    server = Server(cfg["ldaps_fqdn"], port=636, use_ssl=True, tls=tls, connect_timeout=5)
    conn = Connection(server, user=f"{username}@{cfg['ad_domain']}", password=password, receive_timeout=10)
    try:
        if not conn.bind():
            return False
        if group is None:
            return True
        # 1.2.840.113556.1.4.1941: AD's "member of, directly or through nested groups"
        conn.search(cfg["ad_base_dn"], f"(&(sAMAccountName={escape_filter_chars(username)})"
                                       f"(memberOf:1.2.840.113556.1.4.1941:={group}))",
                    attributes=["sAMAccountName"])
        return len(conn.entries) == 1
    finally:
        conn.unbind()


# The signed payload names the kind of session, so a staff member's cookie can never pass
# for an admin's (both are signed with the same key).
def session_cookie(user, kind="admin"):
    payload = f"{kind}|{user}|{int(time.time()) + SESSION_SECONDS}"
    sig = hmac.new(bytes.fromhex(SESSION_KEY.read_text().strip()), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def session_user(cookie, kind="admin"):
    try:
        b64, sig = cookie.split(".", 1)
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        good = hmac.new(bytes.fromhex(SESSION_KEY.read_text().strip()), payload.encode(), hashlib.sha256).hexdigest()
        signed_kind, user, expires = payload.split("|")
        if hmac.compare_digest(sig, good) and signed_kind == kind and time.time() < int(expires):
            return user
    except Exception:                                                  # noqa: BLE001
        pass
    return None


def all_workstations():
    """One row per workstation for the admin page: the fleet (from the deployment
    checkout), guest records, what Proxmox reports, and removals in progress (from
    operations, or from requests the worker hasn't picked up yet)."""
    vms = (L.read_json(L.OBSERVED) or {}).get("vms", {})
    checkins = L.read_json(L.CHECKINS) or {}
    active = {}                                   # host -> the removal operation running on it
    for op in L.ops(200):
        if op["kind"] in ("guest-delete", "fleet-delete") and op["state"] in L.ACTIVE:
            for h in op["hosts"]:
                active.setdefault(h, op)
    rows = {}
    for host, spec in L.fleet().items():
        vm = vms.get(str(spec["vmid"]))
        state = ("ready" if vm and vm["status"] == "running" else
                 "stopped" if vm else "pending")      # pending: the reconciler hasn't built it yet
        rows[host] = {"host": host, "kind": "fleet", "owner": None, "role": spec["role"], "ip": str(spec["ip"]),
                      "vmid": spec["vmid"], "state": state, "error": None, "phases": {}, "removal": None}
    for host, r in L.guests().items():
        rows[host] = {"host": host, "kind": "guest", "owner": r.get("owner"), "role": r.get("role"),
                      "ip": r.get("ip"), "vmid": r.get("vmid"), "state": r.get("state"), "error": r.get("error"),
                      "phases": r.get("phases", {}), "removal": r.get("removal")}
    for host, op in active.items():
        if host in rows:
            rows[host].update(state="removing", removal={"queued": op["created"], **op["steps"]})
    for p in L.REQUESTS.glob("*.json"):           # deletes not picked up yet: show them at once
        q = L.read_json(p) or {}
        if q.get("action") == "delete":
            for h in q.get("hosts") or [f"ws-{q.get('user')}"]:
                if h in rows and rows[h]["state"] != "removing":
                    rows[h].update(state="removing", error=None, removal={"queued": q["time"]})
    for x in rows.values():
        x["checkin"] = checkins.get(x["ip"])
    return sorted(rows.values(), key=lambda x: (x["kind"] != "fleet", x["host"]))


# ---------------------------------------------------------------- the studio's people (/welcome)
# Being able to open this page at all means getting past the site's sign-in gate (the
# "VPN" of the story), so looking someone up by username needs nothing more. Taking
# over an account that exists does: its one-time sign-up link from the welcome email.
# An account that doesn't exist yet can be created from the details in that email.
STAFF_COOKIE = "lab_staff"
PUBKEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|"
                    r"sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}( [^\r\n]{0,100})?$")


def person_view(user, p):
    teams, cat = L.teams(), L.catalog()
    team = teams.get(p.get("team") or "", {})
    return {"username": user, "name": p.get("name"), "given": p.get("given"), "surname": p.get("surname"),
            "title": p.get("title"), "team": p.get("team"), "team_name": team.get("name") or p.get("department"),
            "manager": p.get("manager"), "role": team.get("role") if team.get("role") in cat else None,
            "set_up": p.get("enabled")}


def invite_state(user, token):
    """none (no link for this person), valid, used, expired or wrong."""
    inv = L.read_json(L.INVITES / f"{user}.json")
    if not inv:
        return "none"
    if (L.INVITES / f"{user}.used").exists():
        return "used"
    if not token or not hmac.compare_digest(inv["token_sha256"], sha256(token)):
        return "wrong"
    return "valid" if time.time() < inv["expires"] else "expired"


def my_machines(user):
    """A staff member's workstations for My lab: their records (with the last finished
    configuration run), then requests the worker hasn't picked up yet, so a new machine
    shows up the moment it's asked for."""
    checkins, cat = L.read_json(L.CHECKINS) or {}, L.catalog()
    observed = L.read_json(L.OBSERVED) or {}
    vms = observed.get("vms", {})

    def power(r):
        """Proxmox's view (worker.py reads it every minute and after every power action),
        unless something newer happened since: a machine that just became ready or woke
        up is running, whatever an older snapshot says."""
        if max(r.get("phases", {}).get("ready", 0), r.get("resumed", 0)) > observed.get("time", 0):
            return "running"
        return (vms.get(str(r.get("vmid"))) or {}).get("power")
    keep = ("host", "role", "ip", "vmid", "state", "error", "phases", "removal", "power_action", "power_error")
    found = [{k: r.get(k) for k in keep} | {"checkin": checkins.get(r.get("ip")),
                                            "kind": cat.get(r.get("role"), {}).get("kind"),
                                            "power": power(r)}
             for r in sorted(L.guests().values(), key=lambda r: r.get("vmid") or 0)
             if r.get("staff") and r.get("owner") == user]
    for p in sorted(L.REQUESTS.glob("*.json")):
        q = L.read_json(p) or {}
        if q.get("action") == "staff-create" and q.get("user") == user:
            found.append({"host": None, "role": q["role"], "ip": None, "vmid": None, "state": "building",
                          "error": None, "phases": {"queued": q["time"]}, "removal": None, "checkin": None,
                          "kind": L.catalog().get(q["role"], {}).get("kind"), "power": None})
    return found


def key_info(user):
    """The SSH key someone gave (type, comment, fingerprint as ssh-keygen -l shows it)."""
    try:
        kind, blob, *comment = (L.KEYS / user).read_text(encoding="utf-8").split(maxsplit=2)
        digest = base64.b64encode(hashlib.sha256(base64.b64decode(blob)).digest()).decode().rstrip("=")
        return {"type": kind, "comment": " ".join(comment).strip(), "fingerprint": f"SHA256:{digest}"}
    except (OSError, ValueError):
        return None


def signup_pending(user):
    """True while the worker hasn't taken this person's sign-up yet (it deletes the file).
    The directory can't be listed by the web side, but a known name can be checked."""
    try:
        return (L.SIGNUPS / f"{user}.json").exists()
    except OSError:
        return False


def activity(limit=30):
    keep = ("id", "kind", "actor", "hosts", "state", "steps", "error", "created", "finished")
    return [{k: op.get(k) for k in keep} for op in L.ops(limit)]


# ---------------------------------------------------------------- pages
def render_page(page="portal.html"):
    """A page with the roles, teams and build steps filled in, so the page and the API
    never disagree about them."""
    roles = {k: {"name": v["name"], "desc": v["description"], "tools": v["tools"], "size": v["size"],
                 "kind": v["kind"]} for k, v in L.catalog().items()}
    teams = {k: {"name": v["name"], "role": v["role"]} for k, v in L.teams().items()}
    config = {"roles": roles, "teams": teams, "phases": [p[:2] for p in L.PHASES],
              "limits": L.settings()["staff_limits"], "idle_minutes": L.settings()["idle_hibernate_minutes"]}
    return (HERE / page).read_text(encoding="utf-8").replace("__CONFIG__", json.dumps(config))


STATIC = {"/static/common.css": "text/css", "/static/common.js": "text/javascript"}


class Handler(BaseHTTPRequestHandler):
    server_version = "lab-portal"

    def send(self, status, body, ctype="application/json", headers=()):
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def token(self):
        return self.headers.get("X-Lab-Token", "")

    def admin(self):
        """The signed-in lab admin, if any (from the session cookie)."""
        return self.session(COOKIE, "admin")

    def staff(self):
        """The signed-in staff member, if any (welcome page)."""
        return self.session(STAFF_COOKIE, "staff")

    def session(self, cookie, kind):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == cookie and value:
                return session_user(value, kind)
        return None

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self.send(200, render_page(), "text/html")
        if path == "/admin":
            return self.send(200, (HERE / "admin.html").read_text(encoding="utf-8"), "text/html")
        if path == "/welcome":
            return self.send(200, render_page("welcome.html"), "text/html")
        if path == "/my":
            return self.send(200, render_page("my.html"), "text/html")
        if path == "/mail":
            return self.send(200, (HERE / "mail.html").read_text(encoding="utf-8"), "text/html")
        if path == "/api/mail":
            return self.send(200, L.read_json(L.MAILBOX) or {"emails": []})
        if path == "/api/welcome/lookup":
            q = parse_qs(url.query)
            user = q.get("u", [""])[0].strip().lower()
            p = L.people().get(user) if L.USER_RE.fullmatch(user) else None
            return self.send(200, {"found": bool(p), "person": person_view(user, p) if p else None,
                                   "link": invite_state(user, q.get("t", [""])[0]) if p else "none"})
        if path == "/api/me":
            user = self.staff()
            if not user:
                return self.send(403, {"error": "sign in"})
            p = L.people().get(user)
            return self.send(200, {"user": user, "person": person_view(user, p) if p else None,
                                   "onboarding": L.read_json(L.ONBOARDING / f"{user}.json") or {},
                                   "signup_pending": signup_pending(user), "key": key_info(user),
                                   "machines": my_machines(user)})
        if path in STATIC:
            return self.send(200, (HERE / path.rsplit("/", 1)[1]).read_text(encoding="utf-8"), STATIC[path])
        if path == "/healthz":
            return self.send(200, "ok\n", "text/plain")
        if path == "/api/info":
            return self.send(200, {"in_use": in_use(), "max": L.settings()["max_guests"]})
        if path == "/api/check":
            user = parse_qs(url.query).get("username", [""])[0].strip().lower()
            problem = username_problem(user)
            return self.send(200, {"ok": problem is None, "reason": problem})
        if path == "/api/status":
            r = find(self.token())
            return self.send(200, public_view(r)) if r else self.send(404, {"error": "not found"})
        if path.startswith("/api/admin/"):
            admin = self.admin()
            if path == "/api/admin/me":
                return self.send(200, {"user": admin}) if admin else self.send(403, {"error": "sign in"})
            if not admin:
                return self.send(403, {"error": "sign in"})
            if path == "/api/admin/machines":
                pending = (L.read_json(L.RECONCILE) or {}).get("pending_destroys", [])
                return self.send(200, {"machines": all_workstations(), "pending_destroys": pending,
                                       "steps": L.REMOVAL_STEPS, "phases": [p[:2] for p in L.PHASES],
                                       "roles": {k: v["name"] for k, v in L.catalog().items()}})
            if path == "/api/admin/activity":
                return self.send(200, {"ops": activity()})
        if path.startswith("/m/"):           # links from the first version of the portal
            self.send_response(303)
            self.send_header("Location", "/#t=" + path[3:].strip("/"))
            self.send_header("Content-Length", "0")
            return self.end_headers()
        self.send(404, {"error": "not found"})

    def do_POST(self):
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if self.path == "/api/request":
            return self.create(str(body.get("username", "")).strip().lower(), str(body.get("role", "")))
        if self.path == "/api/delete":
            return self.delete(self.token())
        if self.path == "/api/connect":
            return self.connect(self.token())
        if self.path.startswith(("/api/welcome/", "/api/me/")):
            if self.headers.get("X-Requested-With") != "lab-portal":     # as for admin actions, below
                return self.send(403, {"error": "forbidden"})
            return self.staff_post(self.path, body)
        if self.path.startswith("/api/admin/"):
            # Admin actions come only from the admin page's own fetch() calls. With the
            # SameSite=Strict cookie this header shuts out cross-site form posts twice over.
            if self.headers.get("X-Requested-With") != "lab-portal":
                return self.send(403, {"error": "forbidden"})
            return self.admin_post(self.path, body)
        self.send(404, {"error": "not found"})

    def admin_post(self, path, body):
        if path == "/api/admin/login":
            user = str(body.get("username", "")).strip().lower()
            try:
                ok = ad_admin_login(user, str(body.get("password", "")))
            except Exception as e:                                     # noqa: BLE001
                print(f"admin login: AD check failed: {e!r}", flush=True)
                return self.send(503, {"error": "Couldn't reach the domain controller."})
            print(f"admin login {user!r}: {'ok' if ok else 'refused'}", flush=True)
            if not ok:
                return self.send(403, {"error": "Wrong username or password, or not a lab admin."})
            cookie = (f"{COOKIE}={session_cookie(user)}; Path=/; Max-Age={SESSION_SECONDS}; "
                      "Secure; HttpOnly; SameSite=Strict")
            return self.send(200, {"user": user}, headers=[("Set-Cookie", cookie)])
        if path == "/api/admin/logout":
            return self.send(200, {"ok": True},
                             headers=[("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")])
        admin = self.admin()
        if not admin:
            return self.send(403, {"error": "sign in"})
        hosts = body.get("hosts")
        if not isinstance(hosts, list) or not hosts or len(hosts) > 50:
            return self.send(400, {"error": "Pick at least one workstation."})
        hosts = sorted({str(h) for h in hosts})
        known = {m["host"]: m for m in all_workstations()}
        if path == "/api/admin/delete":
            if (bad := [h for h in hosts if h in L.INFRA or h not in known]):
                return self.send(404, {"error": f"Not a workstation: {', '.join(bad)}."})
            if (busy := [h for h in hosts if known[h]["state"] == "removing"]):
                return self.send(409, {"error": f"Already being deleted: {', '.join(busy)}."})
            request({"action": "delete", "hosts": hosts, "admin": admin})
            print(f"admin {admin} deletes {', '.join(hosts)}", flush=True)
            return self.send(200, {"ok": True, "hosts": hosts})
        if path == "/api/admin/approve":
            pending = set((L.read_json(L.RECONCILE) or {}).get("pending_destroys", []))
            if (bad := [h for h in hosts if h not in pending]):
                return self.send(409, {"error": f"Nothing waits for approval on: {', '.join(bad)}."})
            request({"action": "approve", "hosts": hosts, "admin": admin})
            print(f"admin {admin} approves destroying {', '.join(hosts)}", flush=True)
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})

    # ---------------------------------------------------------------- staff (welcome page)
    def staff_post(self, path, body):
        if path == "/api/welcome/check":
            clean, corrections, problems = L.check_person(body, L.teams())
            if clean["username"] in L.people():
                problems.insert(0, f"'{clean['username']}' already has an account: look it up instead.")
            return self.send(200, {"person": clean, "corrections": corrections, "problems": problems})
        if path == "/api/welcome/signup":
            return self.signup(body)
        if path == "/api/me/login":
            user = str(body.get("username", "")).strip().lower()
            try:
                ok = user in L.people() and ad_login(user, str(body.get("password", "")))
            except Exception as e:                                     # noqa: BLE001
                print(f"staff login: AD check failed: {e!r}", flush=True)
                return self.send(503, {"error": "Couldn't reach the domain controller."})
            print(f"staff login {user!r}: {'ok' if ok else 'refused'}", flush=True)
            if not ok:
                return self.send(403, {"error": "Wrong username or password."})
            return self.send(200, {"user": user}, headers=[("Set-Cookie", self.staff_cookie(user))])
        if path == "/api/me/logout":
            return self.send(200, {"ok": True}, headers=[
                ("Set-Cookie", f"{STAFF_COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")])
        user = self.staff()
        if not user:
            return self.send(403, {"error": "sign in"})
        if path == "/api/me/build":
            role = str(body.get("role", ""))
            if role not in L.catalog():
                return self.send(400, {"error": "Pick a workstation type."})
            queued = [m for m in my_machines(user) if not m["host"]]
            if queued:
                return self.send(409, {"error": "Your last request is still being set up. Try again in a moment."})
            if (why := L.admission(role, owner=user)):
                return self.send(409, {"error": why[0].upper() + why[1:] + "."})
            request({"action": "staff-create", "user": user, "role": role})
            return self.send(200, {"ok": True})
        if path == "/api/me/key":
            pubkey = " ".join(str(body.get("pubkey", "")).split())
            if pubkey and not PUBKEY.fullmatch(pubkey):
                return self.send(400, {"error": "That doesn't look like an SSH public key (the one line in the .pub file)."})
            request({"action": "staff-key", "user": user, "pubkey": pubkey})
            return self.send(200, {"ok": True})
        mine = {m["host"]: m for m in my_machines(user) if m["host"]}
        host = str(body.get("host", ""))
        if host not in mine:
            return self.send(404, {"error": "Not one of your workstations."})
        if path == "/api/me/delete":
            request({"action": "staff-delete", "user": user, "host": host})
            return self.send(200, {"ok": True})
        if path == "/api/me/power":
            action = str(body.get("action", ""))
            if action not in L.Proxmox.POWER:
                return self.send(400, {"error": "Unknown action."})
            if mine[host]["state"] != "ready" or mine[host].get("power_action"):
                return self.send(409, {"error": "Wait for the workstation to finish what it's doing."})
            request({"action": "staff-power", "user": user, "host": host, "op": action})
            return self.send(200, {"ok": True})
        if path == "/api/me/connect":
            r, desktop = L.guests()[host], body.get("mode") == "desktop"
            if r.get("state") != "ready":
                return self.send(409, {"error": "The workstation isn't ready yet."})
            if mine[host].get("power") != "running":
                return self.send(409, {"error": "The workstation is asleep or off. Start it first."})
            if desktop and mine[host]["kind"] != "desktop":
                return self.send(400, {"error": "This workstation has no desktop: open its terminal."})
            try:
                console = console_ticket(r) if desktop else None
            except Exception as e:                                     # noqa: BLE001
                print(f"console ticket for {host} failed: {e!r}", flush=True)
                return self.send(503, {"error": "Couldn't open the desktop. Try again in a moment."})
            return self.send(200, {"url": guacamole_url(*guacamole_login(r, with_password=False, console=console))})
        return self.send(404, {"error": "not found"})

    def staff_cookie(self, user):
        return (f"{STAFF_COOKIE}={session_cookie(user, 'staff')}; Path=/; Max-Age={SESSION_SECONDS}; "
                "Secure; HttpOnly; SameSite=Strict")

    def signup(self, body):
        """Set up an account: claim an existing one (with its sign-up link) or create a
        missing one (from the details in the welcome email), then the first workstation.
        The worker does the AD part; this checks everything it can first."""
        user = str(body.get("username", "")).strip().lower()
        password, role = str(body.get("password", "")), str(body.get("role", ""))
        pubkey = " ".join(str(body.get("pubkey", "")).split())
        p = L.people().get(user) if L.USER_RE.fullmatch(user) else None
        person = None
        if p:
            if p.get("enabled"):
                return self.send(409, {"error": "This account has been set up already. Sign in instead."})
            state = invite_state(user, str(body.get("token", "")))
            if state != "valid":
                return self.send(403, {"error": {
                    "none": "This account can only be set up by the IT team.",
                    "used": "That sign-up link has been used already.",
                    "expired": "That sign-up link has expired. Ask your hiring manager for a new one.",
                    }.get(state, "Open the sign-up link from your welcome email to set up this account.")})
            names = (p.get("given", ""), p.get("surname", ""))
        else:
            person, _, problems = L.check_person({**(body.get("person") or {}), "username": user}, L.teams())
            if problems:
                return self.send(400, {"error": " ".join(problems)})
            del person["username"]                     # the account's name travels separately
            names = (person["given"], person["surname"])
        if role not in L.catalog():
            return self.send(400, {"error": "Pick a workstation type."})
        if password != str(body.get("password2", "")):
            return self.send(400, {"error": "The two passwords are different."})
        if (problems := L.password_problems(password, user, names)):
            return self.send(400, {"error": "Your password needs " + "; ".join(problems) + "."})
        if pubkey and not PUBKEY.fullmatch(pubkey):
            return self.send(400, {"error": "That doesn't look like an SSH public key (the one line in the .pub file)."})
        if (why := L.admission(role, owner=user)):
            return self.send(409, {"error": why[0].upper() + why[1:] + "."})
        if p:   # spend the link: O_EXCL makes it single-use even if two tabs race
            try:
                os.close(os.open(L.INVITES / f"{user}.used", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640))
            except FileExistsError:
                return self.send(403, {"error": "That sign-up link has been used already."})
        try:
            fd = os.open(L.SIGNUPS / f"{user}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self.send(409, {"error": "This account is being set up already."})
        with os.fdopen(fd, "w") as f:
            json.dump({"user": user, "password": password, "person": person, "role": role,
                       "pubkey": pubkey, "time": time.time()}, f)
        print(f"sign-up {user} ({'claim' if p else 'new'}, {role})", flush=True)
        return self.send(200, {"user": user}, headers=[("Set-Cookie", self.staff_cookie(user))])

    def create(self, user, role):
        if role not in L.catalog():
            return self.send(400, {"error": "Pick a role."})
        if (problem := username_problem(user)):
            return self.send(400, {"error": problem})
        if in_use() >= L.settings()["max_guests"]:
            return self.send(409, {"error": "The lab is full. Try again later."})
        # Creating the password file is the reservation: O_EXCL fails if the name is taken.
        try:
            fd = os.open(L.PASSWORDS / user, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            return self.send(409, {"error": f"'{user}' was just taken. Pick another username."})
        with os.fdopen(fd, "w") as f:
            f.write(new_password())
        token = secrets.token_urlsafe(24)
        request({"action": "create", "user": user, "role": role, "token_sha256": sha256(token)})
        self.send(200, {"token": token})

    def delete(self, token):
        r = find(token)
        if not r:
            return self.send(404, {"error": "not found"})
        if r.get("state") not in ("ready", "failed"):
            return self.send(409, {"error": "Wait until the build has finished or failed."})
        request({"action": "delete", "user": r["owner"], "token_sha256": sha256(token)})
        self.send(200, {"ok": True})

    def connect(self, token):
        r = find(token)
        if not r:
            return self.send(404, {"error": "not found"})
        if r.get("state") != "ready":
            return self.send(409, {"error": "The workstation isn't ready yet."})
        try:
            url = guacamole_url(*guacamole_login(r))
        except Exception as e:                                         # noqa: BLE001
            print(f"connect failed for {r['host']}: {e!r}", flush=True)
            return self.send(500, {"error": "Couldn't create the connection."})
        self.send(200, {"url": url})

    def log_message(self, fmt, *args):   # one line per request in the journal; no tokens in URLs
        print(f"{self.command} {self.path.split('?')[0][:40]} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    os.umask(0o027)
    ThreadingHTTPServer.daemon_threads = True
    print(f"lab-portal listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
