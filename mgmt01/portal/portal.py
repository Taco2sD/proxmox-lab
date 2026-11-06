#!/usr/bin/env python3
"""Self-service portal, web side (see docs/self-service.md).

Runs on mgmt01 as the unprivileged user `labportal`, behind nginx. It never touches
git, OpenTofu or AD itself: it only

  * reserves a username (by creating its password file, which fails if it exists),
  * drops a request file into /var/lib/lab-portal/requests/ for the worker (root),
  * reports progress from the status files the worker writes to machines/.

One page (/) does everything: a wizard dialog creates a workstation and the page
follows its progress. The browser keeps each workstation's secret token in
localStorage and sends it in a header (X-Lab-Token), never in a URL, so it doesn't end
up in access logs. Only a hash of the token is stored on disk.

Standard library only, so there is nothing to install or keep updated.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

STATE = Path("/var/lib/lab-portal")
REQUESTS, MACHINES, PASSWORDS = STATE / "requests", STATE / "machines", STATE / "passwords"
MAX_GUESTS = int(os.environ.get("LAB_PORTAL_MAX_GUESTS", "4"))
LISTEN = ("127.0.0.1", 8090)

ROLES = {
    "artist": {"name": "Artist", "desc": "Ubuntu desktop with image and video tools.",
               "tools": ["ImageMagick", "FFmpeg"]},
    "programmer": {"name": "Programmer", "desc": "Ubuntu desktop with a C/C++ and Python toolchain.",
                   "tools": ["GCC", "CMake", "Ninja", "GDB", "Python venv"]},
}
# 3-12 characters: the machine is called ws-<username>, and AD computer names
# (NetBIOS) can't be longer than 15.
USERNAME = re.compile(r"^[a-z][a-z0-9]{2,11}$")
RESERVED = {
    "admin", "administrator", "guest", "krbtgt", "root", "labadmin", "jrhodes", "alice",
    "bob", "ubuntu", "daemon", "nobody", "sync", "games", "test", "user", "ansible",
}
PHASES = [
    ("queued", "Request received", "The portal queued your request."),
    ("recorded", "Committed to git", "Your machine is one new file in the lab's inventory on GitHub."),
    ("identity", "Identity ready", "AD account, DHCP reservation and install record created."),
    ("created", "VM created", "OpenTofu created the virtual machine on Proxmox."),
    ("installing", "Installing Ubuntu", "Network boot and unattended install. About 6 minutes."),
    ("installed", "Joining the domain", "First boot: domain join and role configuration. About 3 minutes."),
    ("ready", "Ready", ""),
]


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_atomic(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def never_built(m):
    """Rejected by the worker before anything was committed."""
    return m.get("state") == "failed" and "recorded" not in m.get("phases", {})


def find(token):
    """The status behind a token: the worker's machine file, or a request it hasn't
    picked up yet."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return None
    digest = sha256(token)
    for path in MACHINES.glob("*.json"):
        m = read_json(path)
        if m and m.get("token_sha256") == digest:
            return m
    for path in REQUESTS.glob("*.json"):
        r = read_json(path)
        if r and r.get("token_sha256") == digest and r.get("action") == "create":
            return {"user": r["user"], "role": r["role"], "host": f"ws-{r['user']}", "ip": "",
                    "state": "building", "error": None, "phases": {"queued": r["time"]}}
    return None


def in_use():
    """Machines that exist or are being built, plus requests not picked up yet."""
    users = {p.stem for p in MACHINES.glob("*.json") if (m := read_json(p)) and not never_built(m)}
    users |= {(read_json(p) or {}).get("user") for p in REQUESTS.glob("*.json")}
    return len(users - {None})


def username_problem(user):
    if not USERNAME.fullmatch(user):
        return "Use 3 to 12 lowercase letters or digits, starting with a letter."
    if user in RESERVED:
        return f"'{user}' is reserved."
    if (PASSWORDS / user).exists():
        return f"'{user}' is already taken."
    return None


def new_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        # AD's complexity rule: at least three character classes
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw):
            return pw


# ---------------------------------------------------------------- lab admins (/admin)
# Admins sign in with their AD account; only members of ws-admins (nested membership
# counts) get in. The password is checked by binding to dc01 over LDAPS (Let's Encrypt
# certificate for dc01.lab.radicallydecent.com, a name that exists only inside the lab,
# verified with the system trust store) and is never stored. A signed cookie then
# carries the session.
DC_HOST = "dc01.lab.radicallydecent.com"
BASE_DN = "DC=ad,DC=lab,DC=internal"
ADMIN_GROUP_DN = "CN=ws-admins,OU=Groups,OU=Lab," + BASE_DN
SAMBA_CA = "/etc/ssl/certs/ca-certificates.crt"
SESSION_KEY = Path("/etc/lab-portal/session-key")
SESSION_SECONDS = 8 * 3600
COOKIE = "lab_admin"
# Never answer 401 here: the VPS in front uses HTTP Basic auth, and a browser that
# gets a 401 for a request carrying those credentials forgets them, so the next
# request is challenged for the demo password again. "Not signed in" is 403.


def ad_admin_login(username, password):
    """True if the AD password is right and the account is in ws-admins."""
    import ssl
    from ldap3 import Connection, Server, Tls                        # python3-ldap3
    from ldap3.utils.conv import escape_filter_chars
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username) or not password:
        return False
    tls = Tls(ca_certs_file=SAMBA_CA, validate=ssl.CERT_REQUIRED)
    server = Server(DC_HOST, port=636, use_ssl=True, tls=tls, connect_timeout=5)
    conn = Connection(server, user=f"{username}@ad.lab.internal", password=password, receive_timeout=10)
    try:
        if not conn.bind():
            return False
        # 1.2.840.113556.1.4.1941: AD's "member of, directly or through nested groups"
        conn.search(BASE_DN, f"(&(sAMAccountName={escape_filter_chars(username)})"
                             f"(memberOf:1.2.840.113556.1.4.1941:={ADMIN_GROUP_DN}))",
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
    except Exception:
        pass
    return None


def all_guests():
    """Every guest machine, whatever its state, plus requests not picked up yet."""
    rows = []
    for path in MACHINES.glob("*.json"):
        m = read_json(path)
        if m:
            rows.append({k: m.get(k) for k in ("user", "role", "host", "ip", "vmid", "state", "error", "phases", "removal")})
    for path in REQUESTS.glob("*.json"):
        r = read_json(path)
        if r and r.get("action") == "delete":
            # Deletion requested, not picked up by the worker yet: show it at once
            for x in rows:
                if x["user"] == r["user"] and x["state"] != "removing":
                    x.update(state="removing", error=None, removal={"queued": r["time"]})
        if r and r.get("action") == "create" and not any(x["user"] == r["user"] for x in rows):
            rows.append({"user": r["user"], "role": r["role"], "host": f"ws-{r['user']}", "ip": "", "vmid": None,
                         "state": "building", "error": None, "phases": {"queued": r["time"]}})
    return sorted(rows, key=lambda x: x["host"])


JSON_KEY = Path("/etc/lab-portal/json-secret-key")   # shared with Guacamole (guacamole.env)


def guacamole_login(m):
    """A Guacamole JSON-auth login for one SSH connection to the visitor's machine,
    valid for 60 seconds. Same steps as Guacamole's reference encrypt-json.sh:
    HMAC-SHA256 the JSON with the key, prepend the signature, AES-128-CBC with a zero IV
    (PKCS#7 padding), base64."""
    from cryptography.hazmat.primitives import padding                  # python3-cryptography
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes.fromhex(JSON_KEY.read_text().strip())
    payload = json.dumps({
        "username": m["user"],
        "expires": int((time.time() + 60) * 1000),                     # milliseconds
        "connections": {m["host"]: {"protocol": "ssh", "parameters": {
            "hostname": m["ip"], "port": "22", "username": m["user"],
            "password": (PASSWORDS / m["user"]).read_text(),
            "color-scheme": "gray-black", "font-size": "11",
        }}},
    }).encode()
    signed = hmac.new(key, payload, hashlib.sha256).digest() + payload
    padder = padding.PKCS7(128).padder()
    padded = padder.update(signed) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def public_view(m):
    """What the browser gets: no token hash, the password only once the machine is ready."""
    view = {k: m.get(k) for k in ("user", "role", "host", "ip", "state", "error", "phases")}
    if m.get("state") == "ready":
        try:
            view["password"] = (PASSWORDS / m["user"]).read_text()
        except OSError:
            view["password"] = None
    return view


# ---------------------------------------------------------------- the page

# portal.html sits next to this file; the roles and build steps are filled in here so
# the page and the API never disagree about them.
PAGE = (Path(__file__).with_name("portal.html")).read_text(encoding="utf-8")
ADMIN_PAGE = (Path(__file__).with_name("admin.html")).read_text(encoding="utf-8")


def render_page():
    config = {"roles": ROLES, "phases": [p[:2] for p in PHASES]}
    return PAGE.replace("__CONFIG__", json.dumps(config))


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "lab-portal"

    def send(self, status, body, ctype="application/json", headers=()):
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
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
        if url.path in ("/", "/index.html"):
            return self.send(200, render_page(), "text/html")
        if url.path == "/admin":
            return self.send(200, ADMIN_PAGE, "text/html")
        if url.path == "/api/admin/me":
            user = self.admin()
            return self.send(200, {"user": user}) if user else self.send(403, {"error": "sign in"})
        if url.path == "/api/admin/machines":
            if not self.admin():
                return self.send(403, {"error": "sign in"})
            return self.send(200, {"machines": all_guests(), "phases": [p[:2] for p in PHASES]})
        if url.path == "/healthz":
            return self.send(200, "ok\n", "text/plain")
        if url.path == "/api/info":
            return self.send(200, {"in_use": in_use(), "max": MAX_GUESTS})
        if url.path == "/api/check":
            user = parse_qs(url.query).get("username", [""])[0].strip().lower()
            problem = username_problem(user)
            return self.send(200, {"ok": problem is None, "reason": problem})
        if url.path == "/api/status":
            m = find(self.token())
            return self.send(200, public_view(m)) if m else self.send(404, {"error": "not found"})
        if url.path.startswith("/m/"):           # links from the first version of the portal
            self.send_response(303)
            self.send_header("Location", "/#t=" + url.path[3:].strip("/"))
            self.send_header("Content-Length", "0")
            return self.end_headers()
        self.send(404, {"error": "not found"})

    def do_POST(self):
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        raw = self.rfile.read(length)
        if self.path == "/api/request":
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad request"})
            return self.create(str(body.get("username", "")).strip().lower(), str(body.get("role", "")))
        if self.path.startswith("/api/admin/"):
            # Admin actions come only from the admin page's own fetch() calls. With the
            # SameSite=Strict cookie this header shuts out cross-site form posts twice over.
            if self.headers.get("X-Requested-With") != "lab-portal":
                return self.send(403, {"error": "forbidden"})
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad request"})
            return self.admin_post(self.path, body)
        if self.path == "/api/delete":
            return self.delete(self.token())
        if self.path == "/api/connect":
            m = find(self.token())
            if not m:
                return self.send(404, {"error": "not found"})
            if m.get("state") != "ready":
                return self.send(409, {"error": "The workstation isn't ready yet."})
            try:
                data = guacamole_login(m)
            except Exception as e:
                print(f"connect failed for {m['user']}: {e!r}", flush=True)
                return self.send(500, {"error": "Couldn't create the connection."})
            # Straight to the connection's own page. Guacamole's home page only jumps into
            # a lone connection on a fresh login; with a session already open it shows
            # "No recent connections". The id is Guacamole's own client identifier:
            # base64 of "<connection>\0c\0<data source>".
            client = base64.b64encode(f"{m['host']}\0c\0json".encode()).decode()
            return self.send(200, {"url": f"/guacamole/#/client/{client}?data=" + quote(data, safe="")})
        self.send(404, {"error": "not found"})

    def admin_post(self, path, body):
        if path == "/api/admin/login":
            user = str(body.get("username", "")).strip().lower()
            ok = False
            try:
                ok = ad_admin_login(user, str(body.get("password", "")))
            except Exception as e:
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
        if path == "/api/admin/delete":
            user = str(body.get("user", ""))
            if not any(m["user"] == user for m in all_guests()):
                return self.send(404, {"error": "No such workstation."})
            write_atomic(REQUESTS / f"{time.time_ns()}-{user}-delete.json",
                         {"action": "delete", "user": user, "admin": admin, "time": time.time()})
            print(f"admin {admin} deletes ws-{user}", flush=True)
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})

    def create(self, user, role):
        if role not in ROLES:
            return self.send(400, {"error": "Pick a role."})
        if (problem := username_problem(user)):
            return self.send(400, {"error": problem})
        if in_use() >= MAX_GUESTS:
            return self.send(409, {"error": f"The lab is full ({MAX_GUESTS} guest workstations). Try again later."})
        # Creating the password file is the reservation: O_EXCL fails if the name is taken.
        try:
            fd = os.open(PASSWORDS / user, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            return self.send(409, {"error": f"'{user}' was just taken. Pick another username."})
        with os.fdopen(fd, "w") as f:
            f.write(new_password())
        token = secrets.token_urlsafe(24)
        write_atomic(REQUESTS / f"{time.time_ns()}-{user}.json",
                     {"action": "create", "user": user, "role": role, "token_sha256": sha256(token), "time": time.time()})
        self.send(200, {"token": token})

    def delete(self, token):
        m = find(token)
        if not m:
            return self.send(404, {"error": "not found"})
        if m.get("state") not in ("ready", "failed"):
            return self.send(409, {"error": "Wait until the build has finished or failed."})
        write_atomic(REQUESTS / f"{time.time_ns()}-{m['user']}-delete.json",
                     {"action": "delete", "user": m["user"], "token_sha256": sha256(token), "time": time.time()})
        self.send(200, {"ok": True})

    def log_message(self, fmt, *args):   # one line per request in the journal; no tokens in URLs
        print(f"{self.command} {self.path.split('?')[0][:40]} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    os.umask(0o027)
    ThreadingHTTPServer.daemon_threads = True
    print(f"lab-portal listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
