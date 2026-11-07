// Shared helpers for the portal's pages (portal.html, admin.html), served by portal.py
// at /static/common.js. Plain browser JavaScript, no build step and no libraries.

const $ = s => document.querySelector(s);

// el("button", { class: "primary", onclick: fn }, "Text", child...): build DOM without
// innerHTML, so text from the server is never parsed as HTML.
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "indeterminate") n[k] = !!v;
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid);
  return n;
};

// fetch() that never throws: { ok, status, data }. Admin calls add X-Requested-With,
// which portal.py requires on every admin POST (see admin_post there).
async function api(path, { body, method, token, admin } = {}) {
  const headers = {};
  if (token) headers["X-Lab-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (admin && body !== undefined) headers["X-Requested-With"] = "lab-portal";
  try {
    const r = await fetch(path, { method: method || (body !== undefined ? "POST" : "GET"), headers, cache: "no-store",
                                  body: body !== undefined ? JSON.stringify(body) : undefined });
    return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
  } catch { return { ok: false, status: 0, data: {} }; }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const clock = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const ago = ts => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago`
       : s < 86400 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m ago` : `${Math.floor(s / 86400)}d ago`;
};
// True while the person has text selected on the page. The pages redraw themselves on a
// timer (replaceChildren), which would drop the selection between selecting and Ctrl+C:
// their refreshes wait while this is true, and row clicks that end a selection don't act.
const selecting = () => { const s = getSelection(); return !!s && !s.isCollapsed && s.toString().trim() !== ""; };
function toast(msg) {
  const t = $("#toast"); if (!t) return;
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2400);
}

// ---- Workstation build progress (welcome.html, my.html)
// A build passes lablib.PHASES (queued, identity, created, joining, ready); the record
// keeps when each was reached. Each step's weight is roughly how many seconds it takes
// in this lab (measured), so the bar moves at about real speed between the records'
// updates instead of jumping. The welcome page puts "account" (the AD account being set
// up) in front of them.
const STEP_WEIGHTS = { account: 5, identity: 15, created: 25, joining: 20, ready: 70 };
const STEP_DOING = {
  account: "Setting up your account",
  identity: "Creating the machine's identity in AD",
  created: "Cloning the lab's golden image",
  joining: "First boot: joining the domain",
  ready: "Installing your software and settings",
};
// order: step keys, first = the start; reached: {step: unix time}. Returns
// { pct (0-100), doing (what's happening now), left (seconds, estimate) }.
function buildProgress(order, reached, now = Date.now() / 1000) {
  let total = 0, done = 0, doing = null;
  for (const k of order.slice(1)) total += STEP_WEIGHTS[k] || 10;
  for (let i = 1; i < order.length; i++) {
    const k = order[i], w = STEP_WEIGHTS[k] || 10;
    if (reached[k]) { done += w; continue; }
    const since = reached[order.slice(0, i).reverse().find(x => reached[x])];
    doing = k;
    if (since) done += w * Math.min(0.95, Math.max(0, now - since) / w);
    break;
  }
  return { pct: Math.round(done / total * 100), doing: doing ? STEP_DOING[doing] : "Ready", left: Math.max(0, Math.round(total - done)) };
}
const aboutLeft = s => s > 90 ? `about ${Math.round(s / 60)} minutes left` : s > 15 ? "about a minute left" : "almost there";

// A role's virtual hardware, as catalog/<role>.yml gives it: "2 vCPU · 3 GB RAM · 24 GB disk"
const specs = size => size ? `${size.cores} vCPU · ${+(size.memory_mb / 1024).toFixed(1)} GB RAM · ${size.disk_gb} GB disk` : "";

// ---- The browser console (my.html, welcome.html)
// Loading Guacamole's app for the first time takes a few seconds, so pages that offer a
// Desktop button load it once in a hidden frame beforehand: the click then only has to
// connect (portal.py: console_ticket).
function warmGuacamole() {
  if (warmGuacamole.done) return;
  warmGuacamole.done = true;
  document.body.append(el("iframe", { src: "/guacamole/", hidden: true, tabindex: "-1", "aria-hidden": "true", title: "" }));
}
