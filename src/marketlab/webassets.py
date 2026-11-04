"""Static assets of the private phone app (PWA). No third-party code, fonts or trackers.

All data is rendered with textContent (never innerHTML), so feed or provider text cannot inject markup.
The service worker caches only the app shell; API, login and callback responses are never cached, so
the phone never shows stale account data as if it were current.
"""
from __future__ import annotations

import html
import struct
import zlib
from functools import lru_cache

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1a22">
<meta name="referrer" content="no-referrer">
<title>MarketLab</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/icon-192.png">
<link rel="stylesheet" href="/app.css">
<script src="/app.js" defer></script>
</head>
<body>
<header>
  <div class="brand"><img src="/icon.svg" alt="" width="28" height="28"><h1>MarketLab</h1></div>
  <p class="scope">Research and paper decisions only. This app cannot place, change or cancel orders.</p>
  <div class="chips" id="chips"></div>
  <p id="offline" class="banner" hidden>Offline: showing no data rather than old data.</p>
</header>
<main>
  <section id="health" class="card"><h2>Health</h2><div class="body"></div>
    <div class="actions">
      <a id="login" class="button primary" href="/login/start">Log in to Kite</a>
      <button id="pause" class="button" type="button">Pause analysis</button>
    </div>
    <p class="hint">Login opens Zerodha's own page. Your password and app code are typed there, never here.</p>
  </section>
  <section id="actual" class="card actual"><h2><span class="tag actual-tag">ACTUAL</span> Your Zerodha account</h2>
    <p class="hint">Read-only broker data. Not simulated.</p><div class="body"></div></section>
  <section id="simulated" class="card simulated"><h2><span class="tag sim-tag">SIMULATED</span> Paper account</h2>
    <p class="hint">Not real money. Never mixed with your actual account.</p><div class="body"></div></section>
  <section id="decisions" class="card"><h2>Decision timeline</h2><div class="body"></div></section>
  <section id="events" class="card"><h2>Upcoming events and new listings</h2><div class="body"></div></section>
  <section id="blockers" class="card"><h2>What is blocking decisions</h2><div class="body"></div></section>
  <section id="budget" class="card"><h2>Storage and running costs</h2><div class="body"></div></section>
</main>
<footer>Private service on your tailnet. Explanations are built from recorded reason codes, not generated text.</footer>
</body>
</html>
"""

APP_CSS = """
:root{--bg:#f4f6f8;--card:#ffffff;--ink:#14212b;--muted:#5b6b78;--line:#dde3e8;--ok:#1f7a4d;--warn:#a15c00;
--bad:#b42318;--actual:#1d4ed8;--sim:#7c3aed;--btn:#e8edf1;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0f1a22;--card:#16242f;--ink:#e8eef2;--muted:#9fb0bd;--line:#2a3b48;
--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--actual:#60a5fa;--sim:#c4b5fd;--btn:#223443}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:max(16px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom))}
header,main,footer{max-width:760px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px}h1{font-size:22px;margin:0}
h2{font-size:17px;margin:0 0 8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.scope,.hint,footer{color:var(--muted);font-size:14px;margin:6px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0}
.actual{border-left:5px solid var(--actual)}.simulated{border-left:5px solid var(--sim)}
.tag{font-size:12px;font-weight:700;letter-spacing:.06em;padding:2px 8px;border-radius:999px;color:#fff}
.actual-tag{background:var(--actual)}.sim-tag{background:var(--sim)}
@media (prefers-color-scheme:dark){.tag{color:#0f1a22}}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.chip{font-size:13px;font-weight:600;border:1px solid var(--line);border-radius:999px;padding:3px 10px}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}
.banner{background:var(--warn);color:#000;padding:8px 12px;border-radius:10px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.button{appearance:none;border:1px solid var(--line);background:var(--btn);color:var(--ink);font:inherit;font-weight:600;
border-radius:10px;padding:10px 14px;text-decoration:none;min-height:44px;display:inline-flex;align-items:center}
.button.primary{background:var(--actual);color:#fff;border-color:transparent}
@media (prefers-color-scheme:dark){.button.primary{color:#0f1a22}}
dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;margin:0}
dt{color:var(--muted)}dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.table{width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line);white-space:nowrap}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.item{border-top:1px solid var(--line);padding:8px 0}.item:first-child{border-top:0}
.muted{color:var(--muted)}.state-STALE,.state-SESSION_UNKNOWN{color:var(--warn)}
.state-MISSING,.state-UNAVAILABLE,.state-MALFORMED{color:var(--bad)}
"""

APP_JS = r"""
"use strict";
const $ = (s, r = document) => r.querySelector(s);
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; }
function money(x) { return x == null ? "unknown" : "₹" + x; }
function age(s) { if (s == null) return "never"; if (s < 90) return s + " s ago"; if (s < 5400) return Math.round(s / 60) + " min ago"; if (s < 172800) return Math.round(s / 3600) + " h ago"; return Math.round(s / 86400) + " days ago"; }
function dl(pairs) { const d = el("dl"); for (const [k, v] of pairs) { d.append(el("dt", k), el("dd", v)); } return d; }
function table(head, rows, numeric) {
  const w = el("div", null, "table"), t = el("table"), tr = el("tr");
  head.forEach((h, i) => tr.append(el("th", h, numeric.includes(i) ? "n" : null))); t.append(tr);
  for (const r of rows) { const row = el("tr"); r.forEach((c, i) => row.append(el("td", c == null ? "unknown" : c, numeric.includes(i) ? "n" : null))); t.append(row); }
  w.append(t); return w;
}
function chip(text, kind) { return el("span", text, "chip " + kind); }
function body(id) { const b = $("#" + id + " .body"); b.replaceChildren(); return b; }

function render(s) {
  const svc = s.service, ses = s.session;
  const kind = svc.state === "RUNNING" ? "ok" : svc.state === "AUTH_REQUIRED" ? "warn" : "bad";
  $("#chips").replaceChildren(chip("Service: " + svc.state, kind), chip("Kite: " + ses.state + (ses.invalidated ? " (invalidated)" : ""), ses.state === "AUTHENTICATED" && !ses.invalidated ? "ok" : "warn"),
    chip("Analysis: " + svc.analysis, svc.analysis === "ACTIVE" ? "ok" : "warn"), chip("Live orders: none", "ok"));
  $("#pause").textContent = svc.analysis === "PAUSED" ? "Resume analysis" : "Pause analysis";
  $("#pause").dataset.action = svc.analysis === "PAUSED" ? "resume" : "pause";
  const h = body("health");
  h.append(dl([["Last broker collection", s.data.broker_last_batch_at ? age(s.data.broker_age_seconds) : "never"],
    ["Kite session", ses.state === "AUTHENTICATED" ? "valid until " + ses.expires_at : (ses.reason || ses.state)],
    ["Scheduler updated", svc.updated_at || "not started"]]));
  const src = Object.entries(s.data.sources).sort();
  if (src.length) h.append(el("h3", "Exchange data received", "muted"), table(["Source", "Received"], src.map(([k, v]) => [k, age(v.age_seconds)]), [1]));
  const jobs = Object.entries(svc.jobs || {});
  if (jobs.length) h.append(el("h3", "Last job results", "muted"), table(["Job", "Result"], jobs.map(([k, v]) => [k, v.result + (v.error ? " (" + v.error + ")" : "")]), []));

  const a = body("actual"), sec = s.actual.sections || {};
  if (!s.actual.batch) a.append(el("p", "No completed broker collection yet.", "muted"));
  else {
    const hd = sec.holdings || {}, f = sec.funds || {}, p = sec.positions || {}, t = sec.trades || {};
    a.append(dl([["Holdings", hd.state === "OK" || hd.state === "STALE" ? hd.count + " stocks" + (hd.state === "STALE" ? " (not from today)" : "") : hd.state],
      ["Invested", money(hd.totals && hd.totals.invested)], ["Current value", money(hd.totals && hd.totals.value)],
      ["Unrealised P&L (before selling costs)", money(hd.totals && hd.totals.pnl)],
      ["Cash", f.state ? (f.state === "OK" || f.state === "STALE" ? money(f.cash) : f.state) : "unknown"],
      ["Positions today", p.count != null ? p.count : (p.state || "unknown")],
      ["Trades", t.state === "OK" ? t.fills + " fills today" : t.state === "STALE" ? "none collected today (last: " + t.session_date + ")" : (t.state || "unknown")]]));
    if (hd.rows && hd.rows.length) a.append(table(["Stock", "Qty", "Avg", "Last", "P&L"], hd.rows.map(r => [r.symbol, r.quantity, r.average_price, r.last_price, r.pnl]), [1, 2, 3, 4]));
  }
  const m = s.simulated, sb = body("simulated");
  sb.append(dl([["Starting cash", money(m.starting_cash)], ["Cash", money(m.cash)], ["Positions", m.positions.length], ["P&L", money(m.pnl)]]), el("p", m.note, "muted"));

  const d = body("decisions");
  if (!s.decisions.length) d.append(el("p", "No decisions recorded yet.", "muted"));
  for (const x of s.decisions) {
    const it = el("div", null, "item");
    it.append(el("strong", x.action + " · " + x.day), el("p", x.explanation), el("p", "Reasons: " + x.reasons.join(", ") + " · model: " + (x.model_id || "none") + " · simulated", "muted"));
    d.append(it);
  }
  const e = body("events"), ev = s.events;
  e.append(el("h3", "Corporate actions (next 14 days)", "muted"));
  if (!ev.corporate_actions.length) e.append(el("p", "None in the stored NSE feed.", "muted"));
  else e.append(table(["Ex-date", "Company", "Purpose"], ev.corporate_actions.map(r => [r.ex_date, r.company, r.purpose]), []));
  e.append(el("h3", "Listings within 14 days", "muted"));
  if (!ev.new_listings.length) e.append(el("p", "None in the stored NSE equity list.", "muted"));
  else e.append(table(["Date", "Symbol", "Name"], ev.new_listings.map(r => [r.listing_date, r.symbol, r.name]), []));

  const b = body("blockers");
  for (const x of s.blockers) { const it = el("div", null, "item"); it.append(el("strong", x.code), el("p", x.text)); b.append(it); }
  if (!s.research_queue.length) b.append(el("p", "Research queue: empty.", "muted"));
  const g = body("budget"), u = s.budget, mb = n => (n / 1048576).toFixed(1) + " MB";
  g.append(dl([["Evidence database", mb(u.evidence_bytes) + " of " + mb(u.evidence_quota_bytes)], ["Exchange files", mb(u.market_files_bytes)], ["Catalog", mb(u.catalog_bytes)]]));
  g.append(table(["Recurring item", "Cost", "State"], u.recurring.map(r => [r.item, r.cost, r.state]), []));
}

async function refresh() {
  try {
    const r = await fetch("/api/status", { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    render(await r.json()); $("#offline").hidden = true;
  } catch (err) {
    $("#offline").hidden = false;
    for (const id of ["actual", "simulated", "decisions", "events", "blockers", "budget"]) body(id);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#pause").addEventListener("click", async (ev) => {
    const action = ev.currentTarget.dataset.action || "pause";
    await fetch("/api/analysis/" + action, { method: "POST", headers: { "X-MarketLab-Action": "1" }, credentials: "same-origin" });
    refresh();
  });
  refresh(); setInterval(refresh, 30000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
});
"""

SERVICE_WORKER = r"""
"use strict";
const SHELL = "marketlab-shell-v1";
const ASSETS = ["/", "/app.js", "/app.css", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !ASSETS.includes(url.pathname)) return; // network only: API, login, callback
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request)));
});
"""

MANIFEST = """{
  "name": "MarketLab research",
  "short_name": "MarketLab",
  "description": "Private research and paper decisions. No order capability.",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#0f1a22",
  "theme_color": "#0f1a22",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}
  ]
}
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0f1a22"/>
<rect x="13" y="34" width="8" height="17" rx="2" fill="#60a5fa"/><rect x="28" y="24" width="8" height="27" rx="2" fill="#60a5fa"/>
<rect x="43" y="14" width="8" height="37" rx="2" fill="#c4b5fd"/></svg>
"""


@lru_cache(maxsize=4)
def icon_png(size: int) -> bytes:
    """The SVG icon's bar chart rasterised without dependencies (solid shapes; maskable safe zone)."""
    bg, blue, violet = (15, 26, 34), (96, 165, 250), (196, 181, 253)
    bars = [(13, 34, 21, 51, blue), (28, 24, 36, 51, blue), (43, 14, 51, 51, violet)]
    s = size / 64
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = x / s, y / s
            color = bg
            for x0, y0, x1, y1, c in bars:
                if x0 <= u < x1 and y0 <= v < y1:
                    color = c
            row += bytes(color)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def message_page(title: str, text: str, link=("/", "Back to the app")) -> str:
    e = html.escape
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer">'
            f'<title>{e(title)}</title><link rel="stylesheet" href="/app.css"></head><body><main>'
            f'<section class="card"><h2>{e(title)}</h2><p>{e(text)}</p>'
            f'<p><a class="button primary" href="{e(link[0])}">{e(link[1])}</a></p></section></main></body></html>')
