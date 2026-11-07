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
function toast(msg) {
  const t = $("#toast"); if (!t) return;
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2400);
}
