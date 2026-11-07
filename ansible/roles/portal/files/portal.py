#!/usr/bin/env python3
"""Self-service portal, web side. Runs on mgmt01 as the unprivileged user labportal.

Deployed to mgmt01:/usr/local/lib/lab-portal/portal.py by roles/portal, run by
lab-portal.service, reached through nginx (roles/lab_web: lab-portal-locations.conf).
docs/self-service.md describes the whole flow.

It never touches git, OpenTofu, Proxmox or AD itself. It can only
  - reserve a username (by creating its password file, which fails if it exists),
  - drop a request file into /var/lib/lab/requests/ for the worker (worker.py, root),
  - read state: guest records, operations, what Proxmox reports (via lablib).

Pages: / (visitors: one tile per machine, build progress, Connect) and /admin (lab
admins, signed in with an AD account in ws-admins: every workstation, multi-select
delete, destroy approvals, Activity). Shared look and helpers: common.css, common.js.

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


def guacamole_login(r):
    """A Guacamole JSON-auth login for one SSH connection to the visitor's machine,
    valid for 60 seconds. Same steps as Guacamole's reference encrypt-json.sh:
    HMAC-SHA256 the JSON with the key, prepend the signature, AES-128-CBC with a zero
    IV (PKCS#7 padding), base64."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes.fromhex(JSON_KEY.read_text().strip())
    payload = json.dumps({
        "username": r["owner"],
        "expires": int((time.time() + 60) * 1000),                       # milliseconds
        "connections": {r["host"]: {"protocol": "ssh", "parameters": {
            "hostname": r["ip"], "port": "22", "username": r["owner"],
            "password": (L.PASSWORDS / r["owner"]).read_text(),
            "color-scheme": "gray-black", "font-size": "11",
        }}},
    }).encode()
    signed = hmac.new(key, payload, hashlib.sha256).digest() + payload
    padder = padding.PKCS7(128).padder()
    padded = padder.update(signed) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


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
    import ssl
    from ldap3 import Connection, Server, Tls                          # python3-ldap3
    from ldap3.utils.conv import escape_filter_chars
    cfg = L.settings()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username) or not password:
        return False
    tls = Tls(ca_certs_file="/etc/ssl/certs/ca-certificates.crt", validate=ssl.CERT_REQUIRED)
    server = Server(cfg["ldaps_fqdn"], port=636, use_ssl=True, tls=tls, connect_timeout=5)
    conn = Connection(server, user=f"{username}@{cfg['ad_domain']}", password=password, receive_timeout=10)
    group = f"CN={cfg['ad_admin_groups'][0]},OU=Groups,OU=Lab,{cfg['ad_base_dn']}"
    try:
        if not conn.bind():
            return False
        # 1.2.840.113556.1.4.1941: AD's "member of, directly or through nested groups"
        conn.search(cfg["ad_base_dn"], f"(&(sAMAccountName={escape_filter_chars(username)})"
                                       f"(memberOf:1.2.840.113556.1.4.1941:={group}))",
                    attributes=["sAMAccountName"])
        return len(conn.entries) == 1
    finally:
        conn.unbind()


def session_cookie(user):
    payload = f"{user}|{int(time.time()) + SESSION_SECONDS}"
    sig = hmac.new(bytes.fromhex(SESSION_KEY.read_text().strip()), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def session_user(cookie):
    try:
        b64, sig = cookie.split(".", 1)
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        good = hmac.new(bytes.fromhex(SESSION_KEY.read_text().strip()), payload.encode(), hashlib.sha256).hexdigest()
        user, expires = payload.rsplit("|", 1)
        if hmac.compare_digest(sig, good) and time.time() < int(expires):
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


def activity(limit=30):
    keep = ("id", "kind", "actor", "hosts", "state", "steps", "error", "created", "finished")
    return [{k: op.get(k) for k in keep} for op in L.ops(limit)]


# ---------------------------------------------------------------- pages
def render_page():
    """portal.html with the roles and build steps filled in, so the page and the API
    never disagree about them."""
    roles = {k: {"name": v["name"], "desc": v["description"], "tools": v["tools"]} for k, v in L.catalog().items()}
    config = {"roles": roles, "phases": [p[:2] for p in L.PHASES]}
    return (HERE / "portal.html").read_text(encoding="utf-8").replace("__CONFIG__", json.dumps(config))


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
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                return session_user(value)
        return None

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self.send(200, render_page(), "text/html")
        if path == "/admin":
            return self.send(200, (HERE / "admin.html").read_text(encoding="utf-8"), "text/html")
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
            data = guacamole_login(r)
        except Exception as e:                                         # noqa: BLE001
            print(f"connect failed for {r['host']}: {e!r}", flush=True)
            return self.send(500, {"error": "Couldn't create the connection."})
        # Straight to the connection's own page. Guacamole's home page only jumps into a
        # lone connection on a fresh login; with a session already open it shows "No
        # recent connections". The id is Guacamole's client identifier:
        # base64 of "<connection>\0c\0<data source>".
        client = base64.b64encode(f"{r['host']}\0c\0json".encode()).decode()
        self.send(200, {"url": f"/guacamole/#/client/{client}?data=" + quote(data, safe="")})

    def log_message(self, fmt, *args):   # one line per request in the journal; no tokens in URLs
        print(f"{self.command} {self.path.split('?')[0][:40]} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    os.umask(0o027)
    ThreadingHTTPServer.daemon_threads = True
    print(f"lab-portal listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
