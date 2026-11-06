#!/usr/bin/env python3
"""Self-service portal, web side (see docs/self-service.md).

Runs on mgmt01 as the unprivileged user `labportal`, behind nginx. It never touches
git, OpenTofu or AD itself: it only

  * reserves a username (by creating its password file, which fails if it exists),
  * drops a request file into /var/lib/lab-portal/requests/ for the worker (root),
  * shows progress from the status files the worker writes to machines/.

Each visitor gets a secret link (/m/<token>). Only a hash of the token is stored, so
the files on disk can't be used to open someone else's page.

Standard library only, so there is nothing to install or keep updated.
"""
import hashlib
import html
import json
import os
import re
import secrets
import string
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

STATE = Path("/var/lib/lab-portal")
REQUESTS, MACHINES, PASSWORDS = STATE / "requests", STATE / "machines", STATE / "passwords"
MAX_GUESTS = int(os.environ.get("LAB_PORTAL_MAX_GUESTS", "4"))
LISTEN = ("127.0.0.1", 8090)

ROLES = {
    "artist": ("Artist", "Ubuntu desktop with image and video tools (ImageMagick, FFmpeg)."),
    "programmer": ("Programmer", "Ubuntu desktop with a build toolchain (GCC, CMake, Ninja, GDB, Python venv)."),
}
# 3-12 characters: the machine is called ws-<username>, and AD computer names
# (NetBIOS) can't be longer than 15.
USERNAME = re.compile(r"^[a-z][a-z0-9]{2,11}$")
RESERVED = {
    "admin", "administrator", "guest", "krbtgt", "root", "labadmin", "jrhodes", "alice",
    "bob", "ubuntu", "daemon", "nobody", "sync", "games", "test", "user", "ansible",
}
PHASES = [
    ("queued", "Request received"),
    ("recorded", "Request committed to git"),
    ("identity", "AD account, network reservation and install record ready"),
    ("created", "Virtual machine created"),
    ("installing", "Installing Ubuntu (about 6 minutes)"),
    ("installed", "Joining the domain and applying the role (about 3 minutes)"),
    ("ready", "Ready"),
]


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def find(token):
    """The status of the request behind a token: the worker's machine file, or the
    still-unprocessed request file."""
    digest = sha256(token)
    for folder in (MACHINES, REQUESTS):
        for path in folder.glob("*.json"):
            data = read_json(path)
            if data and data.get("token_sha256") == digest:
                if folder == REQUESTS:
                    data = {**data, "state": "building", "phases": {"queued": data["time"]}}
                return data
    return None


def guests_in_use():
    """Machines that exist or are being built, plus requests not picked up yet."""
    users = {p.stem for p in MACHINES.glob("*.json")
             if (m := read_json(p)) and not (m["state"] == "failed" and "recorded" not in m["phases"])}
    users |= {(read_json(p) or {}).get("user") for p in REQUESTS.glob("*.json")}
    return len(users - {None})


def new_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        # AD's complexity rule: at least three character classes
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def password_of(user):
    try:
        return (PASSWORDS / user).read_text()
    except OSError:
        return None


# ---------------------------------------------------------------- pages

CSS = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#5d6676; --line:#dde1e7;
        --accent:#2f5bea; --ok:#1d8a4e; --bad:#c23b3b; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14171c; --card:#1d2128; --text:#e6e9ee; --muted:#9aa3b2; --line:#2e343e;
          --accent:#7b9bff; --ok:#4cc38a; --bad:#ff7a7a; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:640px; margin:0 auto; padding:40px 16px; }
h1 { font-size:1.5rem; margin:0 0 4px; }
p.lead { color:var(--muted); margin:0 0 24px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; margin-bottom:16px; }
label { display:block; font-weight:600; margin-bottom:6px; }
input[type=text] { width:100%; padding:10px 12px; font:inherit; color:inherit; background:var(--bg);
                   border:1px solid var(--line); border-radius:8px; }
.hint { color:var(--muted); font-size:.875rem; margin-top:6px; }
.roles { display:grid; gap:10px; margin:18px 0; }
.role { display:flex; gap:10px; align-items:flex-start; border:1px solid var(--line); border-radius:8px; padding:12px; cursor:pointer; }
.role input { margin-top:5px; }
.role span { color:var(--muted); font-size:.875rem; display:block; }
button { font:inherit; font-weight:600; padding:10px 18px; border-radius:8px; border:0; cursor:pointer;
         background:var(--accent); color:#fff; }
button.secondary { background:transparent; color:var(--bad); border:1px solid var(--line); }
.error { color:var(--bad); font-weight:600; }
ol.phases { list-style:none; padding:0; margin:0; }
ol.phases li { padding:6px 0 6px 30px; position:relative; color:var(--muted); }
ol.phases li::before { content:""; position:absolute; left:4px; top:12px; width:12px; height:12px;
                       border-radius:50%; border:2px solid var(--line); }
ol.phases li.done { color:var(--text); }
ol.phases li.done::before { background:var(--ok); border-color:var(--ok); }
ol.phases li.current { color:var(--text); font-weight:600; }
ol.phases li.current::before { border-color:var(--accent); animation:pulse 1.2s infinite; }
@keyframes pulse { 50% { background:var(--accent); } }
ol.phases time { color:var(--muted); font-weight:400; font-size:.8rem; margin-left:6px; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:6px 16px; margin:0; }
dt { color:var(--muted); } dd { margin:0; font-family:ui-monospace, Consolas, monospace; word-break:break-all; }
"""


def page(title, body, status=200):
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><main>{body}</main></body></html>"""
    return status, doc


def form_page(error="", username="", role="artist"):
    radios = "".join(
        f"""<label class="role"><input type="radio" name="role" value="{key}" {"checked" if key == role else ""}>
        <div>{name}<span>{desc}</span></div></label>"""
        for key, (name, desc) in ROLES.items()
    )
    err = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return page("Lab workstations", f"""
<h1>Get a lab workstation</h1>
<p class="lead">Pick a username and a role. The lab creates your AD account and builds an
Ubuntu workstation for you from scratch: PXE boot, unattended install, domain join and
role configuration. It takes about ten minutes, and you can watch every step.</p>
<form class="card" method="post" action="/request">
  {err}
  <label for="username">Username</label>
  <input type="text" id="username" name="username" value="{html.escape(username)}" required
         pattern="[a-z][a-z0-9]{{2,11}}" autocomplete="off" autocapitalize="none" spellcheck="false">
  <div class="hint">3 to 12 lowercase letters or digits, starting with a letter. Your machine will be called ws-&lt;username&gt;.</div>
  <div class="roles">{radios}</div>
  <button type="submit">Build my workstation</button>
</form>""")


def status_page(token, m):
    phases = m.get("phases", {})
    done = [key for key, _ in PHASES if key in phases]
    current = next((key for key, _ in PHASES if key not in phases), None)
    items = []
    for key, label in PHASES:
        cls = "done" if key in phases else ("current" if key == current and m["state"] == "building" else "")
        when = time.strftime("%H:%M:%S", time.localtime(phases[key])) if key in phases else ""
        items.append(f'<li class="{cls}" data-phase="{key}">{label}<time>{when}</time></li>')

    details = ""
    if m["state"] == "ready":
        pw = password_of(m["user"]) or "(not available)"
        details = f"""<div class="card"><h2 style="margin-top:0;font-size:1.1rem">Your workstation</h2><dl>
<dt>Machine</dt><dd>{html.escape(m.get("host", ""))} ({html.escape(m.get("ip", ""))})</dd>
<dt>Username</dt><dd>{html.escape(m["user"])}@ad.lab.internal</dd>
<dt>Password</dt><dd>{html.escape(pw)}</dd></dl>
<p class="hint">Only you and the lab admins can log in to this machine.</p></div>"""
    elif m["state"] == "failed":
        details = f"""<div class="card"><p class="error">The build stopped: {html.escape(m.get("error") or "unknown error")}</p>
<p class="hint">The lab admin can see the full log on mgmt01 (/var/log/lab-portal/).</p></div>"""
    elif m["state"] == "removing":
        details = '<div class="card"><p>Removing this workstation and its account…</p></div>'

    remove = ""
    if m["state"] in ("ready", "failed"):
        remove = f"""<form method="post" action="/m/{token}/delete"
          onsubmit="return confirm('Delete this workstation and your account?')">
          <button class="secondary" type="submit">Delete my workstation</button></form>"""

    name = ROLES.get(m.get("role"), (m.get("role", ""),))[0]
    live = "" if m["state"] in ("ready", "failed") else f"""<script>
const es = new EventSource("/m/{token}/events");
es.onmessage = () => location.reload();   // the server only sends when something changed
</script>"""
    return page(f"{m['user']}: lab workstation", f"""
<h1>{html.escape(m["user"])} · {html.escape(name)}</h1>
<p class="lead">Keep this page: its address is the only way back to your workstation.</p>
<div class="card"><ol class="phases">{"".join(items)}</ol></div>
{details}{remove}{live}""")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "lab-portal"

    def send(self, status, body, ctype="text/html; charset=utf-8", headers=()):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, where):
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def token_route(self):
        match = re.fullmatch(r"/m/([A-Za-z0-9_-]{20,64})(/events|/delete)?", self.path.split("?")[0])
        return (match.group(1), match.group(2) or "") if match else (None, None)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(*form_page())
        if self.path == "/healthz":
            return self.send(200, "ok\n", "text/plain")
        token, sub = self.token_route()
        m = find(token) if token else None
        if not m:
            return self.send(*page("Not found", "<h1>Not found</h1><p><a href='/'>Request a workstation</a></p>", 404))
        if sub == "/events":
            return self.events(token)
        if sub == "":
            return self.send(*status_page(token, m))
        self.send(405, "method not allowed\n", "text/plain")

    def do_POST(self):
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode(errors="replace")).items()}
        if self.path == "/request":
            return self.create(form.get("username", "").strip().lower(), form.get("role", ""))
        token, sub = self.token_route()
        if token and sub == "/delete":
            return self.delete(token)
        self.send(404, "not found\n", "text/plain")

    def create(self, user, role):
        if role not in ROLES:
            return self.send(*form_page("Pick a role.", user, "artist"))
        if not USERNAME.fullmatch(user):
            return self.send(*form_page("Use 3 to 12 lowercase letters or digits, starting with a letter.", user, role))
        if user in RESERVED:
            return self.send(*form_page(f"'{user}' is reserved. Pick another username.", user, role))
        if guests_in_use() >= MAX_GUESTS:
            return self.send(*form_page(f"The lab is full ({MAX_GUESTS} guest workstations). Try again later.", user, role))
        # Creating the password file is the reservation: O_EXCL fails if the name is taken.
        try:
            fd = os.open(PASSWORDS / user, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            return self.send(*form_page(f"'{user}' is already taken. Pick another username.", user, role))
        with os.fdopen(fd, "w") as f:
            f.write(new_password())
        token = secrets.token_urlsafe(24)
        request = {"action": "create", "user": user, "role": role,
                   "token_sha256": sha256(token), "time": time.time()}
        write_atomic(REQUESTS / f"{time.time_ns()}-{user}.json", request)
        self.redirect(f"/m/{token}")

    def delete(self, token):
        m = find(token)
        if not m or m.get("state") not in ("ready", "failed"):
            return self.redirect(f"/m/{token}")
        write_atomic(REQUESTS / f"{time.time_ns()}-{m['user']}-delete.json",
                     {"action": "delete", "user": m["user"], "token_sha256": sha256(token), "time": time.time()})
        self.redirect(f"/m/{token}")

    def events(self, token):
        """Server-Sent Events: one message whenever the request's status changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")   # nginx: pass each event on at once
        self.end_headers()
        last, quiet = json.dumps(find(token), sort_keys=True), 0
        try:
            while True:
                time.sleep(1)
                m = find(token)
                now = json.dumps(m, sort_keys=True)
                if now != last:
                    self.wfile.write(b"data: changed\n\n")
                    self.wfile.flush()
                    last, quiet = now, 0
                    if not m or m.get("state") in ("ready", "failed"):
                        return
                elif (quiet := quiet + 1) >= 15:
                    self.wfile.write(b": keepalive\n\n")   # keeps proxies from closing the stream
                    self.wfile.flush()
                    quiet = 0
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt, *args):   # one line per request in the journal, no IPs (always nginx)
        print(f"{self.command} {self.path.split('/events')[0][:40]} {args[1] if len(args) > 1 else ''}", flush=True)


def write_atomic(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


if __name__ == "__main__":
    os.umask(0o027)
    ThreadingHTTPServer.daemon_threads = True
    print(f"lab-portal listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
