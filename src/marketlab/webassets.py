"""Static assets of the private dashboard (installable PWA). No third-party code, fonts or trackers.

All data is rendered with textContent (never innerHTML), so feed or provider text cannot inject markup. Charts
are inline SVG built from numbers. The service worker caches only the app shell; API, login and callback
responses are never cached, so the page never shows stale account data as if it were current.
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
  <div class="brand"><img src="/icon.svg" alt="" width="28" height="28"><h1>MarketLab</h1>
    <span class="scope">research and paper decisions only; this app cannot place, change or cancel orders</span></div>
  <div class="chips" id="chips"></div>
  <p id="offline" class="banner" hidden>Offline or server unavailable: showing nothing rather than old data.</p>
  <nav id="tabs" aria-label="Sections">
    <button data-tab="overview" class="on" type="button">Overview</button>
    <button data-tab="data" type="button">Data</button>
    <button data-tab="universe" type="button">Universe</button>
    <button data-tab="forecasts" type="button">Forecasts</button>
    <button data-tab="evaluation" type="button">Evaluation</button>
    <button data-tab="research" type="button">Research</button>
    <button data-tab="controls" type="button">Controls</button>
  </nav>
</header>
<main>
  <section id="tab-overview" class="tab"></section>
  <section id="tab-data" class="tab" hidden></section>
  <section id="tab-universe" class="tab" hidden></section>
  <section id="tab-forecasts" class="tab" hidden></section>
  <section id="tab-evaluation" class="tab" hidden></section>
  <section id="tab-research" class="tab" hidden></section>
  <section id="tab-controls" class="tab" hidden></section>
</main>
<footer>Private service on loopback or your tailnet. Explanations are assembled from recorded reason codes, never generated text.</footer>
</body>
</html>
"""

APP_CSS = """
:root{--bg:#f4f6f8;--card:#fff;--ink:#14212b;--muted:#5b6b78;--line:#dde3e8;--ok:#1f7a4d;--warn:#a15c00;--bad:#b42318;
--actual:#1d4ed8;--sim:#7c3aed;--btn:#e8edf1;--bar:#60a5fa;--bar2:#c4b5fd;--neg:#f87171;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0f1a22;--card:#16242f;--ink:#e8eef2;--muted:#9fb0bd;--line:#2a3b48;--ok:#4ade80;
--warn:#fbbf24;--bad:#f87171;--actual:#60a5fa;--sim:#c4b5fd;--btn:#223443;--bar:#60a5fa;--bar2:#a78bfa;--neg:#f87171}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:max(12px,env(safe-area-inset-top)) 14px max(24px,env(safe-area-inset-bottom))}
header,main,footer{max-width:1180px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;flex-wrap:wrap}h1{font-size:22px;margin:0}
.scope,.hint,footer,.muted{color:var(--muted);font-size:13px}
h2{font-size:16px;margin:0 0 8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}h3{font-size:14px;margin:12px 0 4px;color:var(--muted)}
nav#tabs{display:flex;gap:6px;overflow-x:auto;padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:10px}
nav#tabs button{flex:0 0 auto;border:1px solid var(--line);background:var(--btn);color:var(--ink);font:inherit;font-weight:600;
border-radius:999px;padding:6px 14px;cursor:pointer}nav#tabs button.on{background:var(--actual);color:#fff;border-color:transparent}
@media (prefers-color-scheme:dark){nav#tabs button.on{color:#0f1a22}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:0 0 12px}
.card.wide{grid-column:1/-1}.actual{border-left:5px solid var(--actual)}.simulated{border-left:5px solid var(--sim)}
.tag{font-size:11px;font-weight:700;letter-spacing:.06em;padding:2px 8px;border-radius:999px;color:#fff}
.actual-tag{background:var(--actual)}.sim-tag{background:var(--sim)}
@media (prefers-color-scheme:dark){.tag{color:#0f1a22}}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.chip{font-size:12px;font-weight:600;border:1px solid var(--line);border-radius:999px;padding:3px 10px;white-space:nowrap}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}
.banner{background:var(--warn);color:#000;padding:8px 12px;border-radius:10px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
.button{appearance:none;border:1px solid var(--line);background:var(--btn);color:var(--ink);font:inherit;font-weight:600;
border-radius:10px;padding:8px 12px;text-decoration:none;min-height:40px;display:inline-flex;align-items:center;cursor:pointer}
.button.primary{background:var(--actual);color:#fff;border-color:transparent}
@media (prefers-color-scheme:dark){.button.primary{color:#0f1a22}}
dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 12px;margin:0}dt{color:var(--muted)}
dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.table{width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:5px 4px;border-bottom:1px solid var(--line);white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.item{border-top:1px solid var(--line);padding:8px 0}.item:first-child{border-top:0}
.state-STALE,.state-SESSION_UNKNOWN,.st-QUEUED,.st-RUNNING{color:var(--warn)}.state-MISSING,.state-UNAVAILABLE,.state-MALFORMED,.st-FAILED{color:var(--bad)}.st-DONE{color:var(--ok)}
svg.chart{width:100%;height:auto;display:block;margin:6px 0}svg text{fill:var(--muted);font-size:10px}
.pos{color:var(--ok)}.neg{color:var(--bad)}
form.policy{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}
form.policy label{display:flex;flex-direction:column;font-size:12px;color:var(--muted)}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);min-height:36px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
"""

APP_JS = r"""
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; }
function money(x) { return x == null ? "unknown" : "₹" + (typeof x === "number" ? x.toFixed(2) : x); }
function pct(x, d = 2) { return x == null || Number.isNaN(x) ? "unknown" : (100 * x).toFixed(d) + "%"; }
function num(x, d = 4) { return x == null || Number.isNaN(x) ? "unknown" : Number(x).toFixed(d); }
function age(s) { if (s == null) return "never"; if (s < 90) return s + " s ago"; if (s < 5400) return Math.round(s / 60) + " min ago"; if (s < 172800) return Math.round(s / 3600) + " h ago"; return Math.round(s / 86400) + " days ago"; }
function dl(pairs) { const d = el("dl"); for (const [k, v] of pairs) { d.append(el("dt", k), el("dd", v)); } return d; }
function table(head, rows, numeric = [], cls = {}) {
  const w = el("div", null, "table"), t = el("table"), tr = el("tr");
  head.forEach((h, i) => tr.append(el("th", h, numeric.includes(i) ? "n" : null))); t.append(tr);
  for (const r of rows) { const row = el("tr"); r.forEach((c, i) => { const td = el("td", c == null ? "unknown" : c, numeric.includes(i) ? "n" : null); if (cls[i]) td.classList.add(cls[i](c)); row.append(td); }); t.append(row); }
  w.append(t); return w;
}
function chip(text, kind) { return el("span", text, "chip " + kind); }
function card(title, cls) { const c = el("section", null, "card" + (cls ? " " + cls : "")); if (title) c.append(el("h2", title)); return c; }
function tab(id) { const t = $("#tab-" + id); t.replaceChildren(); return t; }
const SVG = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) { const e = document.createElementNS(SVG, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
function barChart(items, opts = {}) {
  // items: [{label, value}]; horizontal bars with sign colouring
  const W = 600, rowH = 18, H = items.length * rowH + 8, max = Math.max(1e-9, ...items.map(i => Math.abs(i.value || 0)));
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  items.forEach((it, i) => {
    const v = it.value || 0, w = Math.abs(v) / max * 300, y = i * rowH + 4;
    s.append(svgEl("rect", { x: v >= 0 ? 260 : 260 - w, y, width: w, height: rowH - 6, fill: v >= 0 ? (opts.color || "var(--bar)") : "var(--neg)", rx: 2 }));
    const t = svgEl("text", { x: 4, y: y + 10 }); t.textContent = String(it.label).slice(0, 34); s.append(t);
    const tv = svgEl("text", { x: 570, y: y + 10, "text-anchor": "end" }); tv.textContent = opts.fmt ? opts.fmt(v) : v.toFixed(2); s.append(tv);
  });
  s.append(svgEl("line", { x1: 260, y1: 0, x2: 260, y2: H, stroke: "var(--line)" }));
  return s;
}
function lineChart(series, opts = {}) {
  // series: [{name, values:[y...]}] plotted on a shared x index
  const W = 600, H = 160, pad = 28, all = series.flatMap(s => s.values).filter(v => v != null);
  if (!all.length) return el("p", "no data", "muted");
  const lo = Math.min(...all), hi = Math.max(...all), n = Math.max(...series.map(s => s.values.length));
  const sx = x => pad + x / Math.max(1, n - 1) * (W - pad - 6), sy = y => H - pad + (lo === hi ? 0 : -(y - lo) / (hi - lo) * (H - pad - 8));
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  const colors = ["var(--bar)", "var(--bar2)", "var(--ok)", "var(--warn)", "var(--neg)"];
  series.forEach((sr, k) => {
    const d = sr.values.map((v, i) => (i === 0 ? "M" : "L") + sx(i).toFixed(1) + " " + sy(v).toFixed(1)).join(" ");
    s.append(svgEl("path", { d, fill: "none", stroke: colors[k % colors.length], "stroke-width": 1.5 }));
  });
  if (opts.baseline != null && opts.baseline >= lo && opts.baseline <= hi) s.append(svgEl("line", { x1: pad, y1: sy(opts.baseline), x2: W - 6, y2: sy(opts.baseline), stroke: "var(--line)", "stroke-dasharray": "4 3" }));
  const t1 = svgEl("text", { x: 2, y: 12 }); t1.textContent = hi.toFixed(0); const t2 = svgEl("text", { x: 2, y: H - pad }); t2.textContent = lo.toFixed(0);
  s.append(t1, t2); return s;
}
function histogram(values, bins = 10) {
  const counts = new Array(bins).fill(0); for (const v of values) { if (v == null) continue; counts[Math.min(bins - 1, Math.max(0, Math.floor(v * bins)))]++; }
  return barChart(counts.map((c, i) => ({ label: (i / bins).toFixed(1) + "-" + ((i + 1) / bins).toFixed(1), value: c })), { fmt: v => String(v) });
}
async function get(path) { const r = await fetch(path, { cache: "no-store", credentials: "same-origin" }); if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "X-MarketLab-Action": "1", "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || ("HTTP " + r.status)); return j;
}

// ---- overview ------------------------------------------------------------------------------------
function renderOverview(s) {
  const svc = s.service, ses = s.session;
  const kind = svc.state === "RUNNING" ? "ok" : svc.state === "AUTH_REQUIRED" ? "warn" : svc.state === "NOT_STARTED" ? "warn" : "bad";
  const schedOld = svc.scheduler_age_seconds == null || svc.scheduler_age_seconds > 300;
  $("#chips").replaceChildren(chip("Service: " + svc.state, kind), chip("Kite: " + ses.state + (ses.invalidated ? " (invalidated)" : ""), ses.state === "AUTHENTICATED" && !ses.invalidated ? "ok" : "warn"),
    chip("Analysis: " + svc.analysis, svc.analysis === "ACTIVE" ? "ok" : "warn"), chip("Scheduler: " + (schedOld ? "not running (" + age(svc.scheduler_age_seconds) + ")" : age(svc.scheduler_age_seconds)), schedOld ? "warn" : "ok"),
    chip("Live orders: none", "ok"));
  const t = tab("overview"), g = el("div", null, "grid"); t.append(g);
  const h = card("Health"); g.append(h);
  const cal = svc.calendar || {};
  h.append(dl([["Last broker collection", s.data.broker_last_batch_at ? age(s.data.broker_age_seconds) : "never"],
    ["Kite session", ses.state === "AUTHENTICATED" ? "valid until " + ses.expires_at : (ses.reason || ses.state)],
    ["Scheduler updated", svc.updated_at || "not started"], ["Last gap", svc.last_gap ? svc.last_gap.minutes + " min ending " + svc.last_gap.to : "none"],
    ["Calendar source", (cal.source || "unknown") + (cal.years ? " (" + cal.years.join(", ") + ")" : "")],
    ["Calendar discrepancies", cal.discrepancies && Object.keys(cal.discrepancies).length ? Object.keys(cal.discrepancies).join(", ") : "none"]]));
  const jobs = Object.entries(svc.jobs || {});
  if (jobs.length) h.append(el("h3", "Last job results"), table(["Job", "At", "Result"], jobs.map(([k, v]) => [k, v.at, v.result + (v.error ? " (" + v.error + ")" : "")])));
  const a = card("Your Zerodha account", "actual"); a.querySelector("h2").prepend(el("span", "ACTUAL", "tag actual-tag")); g.append(a);
  const sec = s.actual.sections || {};
  if (!s.actual.batch) a.append(el("p", "No completed broker collection yet.", "muted"));
  else {
    const hd = sec.holdings || {}, f = sec.funds || {}, p = sec.positions || {}, tr = sec.trades || {};
    a.append(dl([["Holdings", hd.count != null ? hd.count + " stocks" + (hd.state !== "OK" ? " (" + hd.state + ")" : "") : (hd.state || "unknown")],
      ["Invested", money(hd.totals && hd.totals.invested)], ["Current value", money(hd.totals && hd.totals.value)], ["Unrealised P&L (before selling costs)", money(hd.totals && hd.totals.pnl)],
      ["Cash", f.cash != null ? money(f.cash) : (f.state || "unknown")], ["Positions today", p.count != null ? p.count : (p.state || "unknown")],
      ["Trades", tr.state === "OK" ? tr.fills + " fills today" : tr.state === "STALE" ? "none today (last: " + tr.session_date + ")" : (tr.state || "unknown")]]));
    if (hd.rows && hd.rows.length) a.append(table(["Stock", "Qty", "Avg", "Last", "P&L"], hd.rows.map(r => [r.symbol, r.quantity, r.average_price, r.last_price, r.pnl]), [1, 2, 3, 4]));
  }
  const m = s.simulated, sb = card("Paper account", "simulated"); sb.querySelector("h2").prepend(el("span", "SIMULATED", "tag sim-tag")); g.append(sb);
  sb.append(dl([["Starting cash", money(m.starting_cash)], ["Cash", money(m.cash)], ["Positions", m.positions.length], ["P&L", money(m.pnl)]]), el("p", m.note, "muted"));
  const ld = card("Latest decision"); g.append(ld);
  if (!s.latest_decision) ld.append(el("p", "No decision run yet (Controls → Decide).", "muted"));
  else { const d = s.latest_decision; ld.append(dl([["Session", d.day], ["Action", d.action], ["Reasons", (d.reasons || []).join(", ") || "none"], ["Candidate / horizon", d.candidate + " / " + d.h + " sessions"], ["Forecasts produced", d.forecasts], ["Planned quantities", Object.keys(d.plan || {}).length ? JSON.stringify(d.plan) : "none"]])); }
  const dec = card("Decision timeline", "wide"); g.append(dec);
  if (!s.decisions.length) dec.append(el("p", "No decisions recorded yet.", "muted"));
  for (const x of s.decisions) { const it = el("div", null, "item"); it.append(el("strong", x.action + " · " + x.day + (x.late_start ? " (late start)" : "")), el("p", x.explanation), el("p", "Reasons: " + (x.reasons || []).join(", ") + " · model: " + (x.model_id || "none") + " · simulated", "muted")); dec.append(it); }
  const e = card("Upcoming corporate actions and listings"); g.append(e); const ev = s.events;
  e.append(el("h3", "Ex-dates in the next 14 days"));
  e.append(ev.corporate_actions.length ? table(["Ex-date", "Company", "Purpose"], ev.corporate_actions.map(r => [r.ex_date, r.company, r.purpose])) : el("p", "None in the stored NSE feed.", "muted"));
  e.append(el("h3", "Listings within 14 days"));
  e.append(ev.new_listings.length ? table(["Date", "Symbol", "Name"], ev.new_listings.map(r => [r.listing_date, r.symbol, r.name])) : el("p", "None in the stored NSE equity list.", "muted"));
  const b = card("What blocks decisions"); g.append(b);
  for (const x of s.blockers) { const it = el("div", null, "item"); it.append(el("strong", x.code), el("p", x.text)); b.append(it); }
  const u = s.budget, mb = n => (n / 1048576).toFixed(1) + " MB", bc = card("Storage and running costs"); g.append(bc);
  bc.append(dl([["Evidence database", mb(u.evidence_bytes) + " of " + mb(u.evidence_quota_bytes)], ["Exchange files", mb(u.market_files_bytes)], ["Catalog", mb(u.catalog_bytes)], ["Price panel", mb(u.panel_bytes || 0)]]));
  bc.append(table(["Recurring item", "Cost", "State"], u.recurring.map(r => [r.item, r.cost, r.state])));
}

// ---- data ---------------------------------------------------------------------------------------
async function renderData() {
  const t = tab("data"); t.append(el("p", "Loading…", "muted"));
  const d = await get("/api/data"); t.replaceChildren();
  const g = el("div", null, "grid"); t.append(g);
  const pc = card("Price panel"); g.append(pc);
  pc.append(d.panel ? dl([["Sessions", d.panel.sessions], ["First", d.panel.first], ["Last", d.panel.last], ["Securities", d.panel.isins], ["Exchange-implied factors", d.panel.implied_factors]]) : el("p", "Panel not built (Controls → Build panel).", "muted"));
  const mc = card("Security master snapshots"); g.append(mc);
  mc.append(d.master.length ? el("p", d.master.join(", ")) : el("p", "none", "muted"));
  const sc = card("Official files stored", "wide"); g.append(sc);
  const names = Object.keys(d.sources).sort();
  if (!names.length) sc.append(el("p", "No files collected yet.", "muted"));
  else sc.append(table(["Source", "Files", "First", "Last", "Missing trading days (last 30)"], names.map(n => { const s = d.sources[n]; const miss = (d.missing_recent[n] || []); return [n, s.count, s.first, s.last, miss.length ? miss.length + ": " + miss.slice(0, 6).join(", ") + (miss.length > 6 ? "…" : "") : "none"]; }), [1]));
  if (d.missing_recent_error) sc.append(el("p", "Missing-day check unavailable: " + d.missing_recent_error, "muted"));
  const bar = card("Files per source", "wide"); g.append(bar);
  bar.append(barChart(names.map(n => ({ label: n, value: d.sources[n].count })), { fmt: v => String(v) }));
}

// ---- universe ------------------------------------------------------------------------------------
async function renderUniverse(dateStr) {
  const t = tab("universe"); const ctl = card("Dated universe screen (spec 3.1)"); t.append(ctl);
  const row = el("div", null, "row"); const lab = el("label", "Decision session"); const inp = el("input"); inp.type = "date"; if (dateStr) inp.value = dateStr; lab.append(inp);
  const go = el("button", "Screen", "button"); go.type = "button"; go.addEventListener("click", () => renderUniverse(inp.value)); row.append(lab, go); ctl.append(row);
  const body = el("div"); t.append(body); body.append(el("p", "Loading…", "muted"));
  const u = await get("/api/universe" + (dateStr ? "?date=" + encodeURIComponent(dateStr) : "")); body.replaceChildren();
  if (u.error) { body.append(el("p", u.error === "PANEL_NOT_BUILT" ? "Panel not built yet (Controls → Build panel)." : u.error, "muted")); return; }
  const g = el("div", null, "grid"); body.append(g);
  const sm = card("Result for " + u.day); g.append(sm);
  sm.append(dl([["Kept", u.kept], ["Unverified", u.unverified.length ? u.unverified.join(", ") : "none"], ["Minimum median value", "₹" + u.policy.v_min_crore + " crore"], ["Capital", money(u.policy.capital)]]));
  const ex = card("Exclusions"); g.append(ex);
  const items = Object.entries(u.stats).filter(([k]) => k !== "kept").map(([k, v]) => ({ label: k, value: v }));
  ex.append(items.length ? barChart(items, { fmt: v => String(v) }) : el("p", "none", "muted"));
  const tb = card("Members (first 300)", "wide"); g.append(tb);
  tb.append(u.rows.length ? table(["Symbol", "ISIN", "Close", "Traded value (₹ crore)"], u.rows.map(r => [r.symbol, r.isin, r.close, r.value_crore]), [2, 3]) : el("p", "No security passes the screen on this day.", "muted"));
}

// ---- forecasts -----------------------------------------------------------------------------------
async function renderForecasts() {
  const t = tab("forecasts"); t.append(el("p", "Loading…", "muted"));
  const r = await get("/api/decision"); t.replaceChildren();
  if (!r.decision) { t.append(card("Forecasts").appendChild(el("p", "No decision run yet (Controls → Decide). Forecasts are research diagnostics until a candidate is promoted.", "muted")).parentNode); return; }
  const d = r.decision, g = el("div", null, "grid"); t.append(g);
  const h = card("Decision for " + d.day); g.append(h);
  h.append(dl([["Action", d.action], ["Reasons", (d.reasons || []).join(", ") || "none"], ["Candidate / horizon", d.candidate + " / " + d.h], ["Generated", d.generated_at], ["Universe kept", d.universe ? d.universe.kept : "unknown"], ["Unverified", d.universe && d.universe.unverified.length ? d.universe.unverified.join(", ") : "none"]]));
  const m = d.model || {}, mc = card("Model"); g.append(mc);
  const zq = m.z_quantiles || {};
  mc.append(dl([["Target", m.target_id], ["Lambda", m.lam], ["Training rows", m.n_train], ["Training dates", (m.train || []).join(" → ")], ["Calibration residuals", m.calibration_n], ["z quantiles (10/50/90)", [zq["0.1"], zq["0.5"], zq["0.9"]].map(v => num(v, 2)).join(" / ")], ["Bootstrap refits", m.bootstraps]]));
  const pl = card("Allocation plan (" + money(d.policy && d.policy.W) + ", K=" + (d.policy && d.policy.K) + ")"); g.append(pl);
  const q = (d.plan && d.plan.quantities) || {}, vals = (d.plan && d.plan.values) || {};
  pl.append(Object.keys(q).length ? table(["ISIN", "Quantity", "Value"], Object.keys(q).map(k => [k, q[k], money(vals[k])]), [1, 2]) : el("p", (d.plan && d.plan.note) || "No position passes the gate: " + JSON.stringify((d.plan && d.plan.rejected) || {}).slice(0, 300), "muted"));
  const fc = card("Forecasts (gross excess return over the horizon; shrunk mean drives decisions)", "wide"); g.append(fc);
  const rows = (d.forecasts || []).filter(f => f.mu_shrunk != null);
  fc.append(barChart(rows.slice(0, 20).map(f => ({ label: f.symbol || f.isin, value: f.mu_shrunk })), { fmt: v => pct(v) }));
  fc.append(table(["Symbol", "Close", "μ̂", "se", "μ̃ shrunk", "q10", "q50", "q90", "P(>0)", "σ̂", "Slippage"],
    rows.map(f => [f.symbol || f.isin, f.close, pct(f.mu_hat), pct(f.se), pct(f.mu_shrunk), pct(f.q10), pct(f.q50), pct(f.q90), num(f.p_positive, 3), pct(f.sigma_hat), pct(f.slippage)]), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]));
  const ab = (d.forecasts || []).filter(f => f.abstain); if (ab.length) fc.append(el("p", ab.length + " securities abstained: " + ab[0].abstain, "muted"));
}

// ---- evaluation ----------------------------------------------------------------------------------
async function renderEvaluation(trial) {
  const t = tab("evaluation"); t.append(el("p", "Loading…", "muted"));
  const list = await get("/api/evaluation"); t.replaceChildren();
  const lc = card("Registered trials (walk-forward reports)"); t.append(lc);
  if (!list.reports.length) { lc.append(el("p", "No evaluation has been run. Needs the historical backfill; see docs/FABLE_SESSION_1_SPEC.md section 8.", "muted")); return; }
  lc.append(table(["Trial", "Generated", "Folds", "Trades", "Net ₹", "Folds > 0", "80% coverage", "Brier skill", "Sharpe/trade"],
    list.reports.map(r => [r.trial_id, r.generated_at, r.folds_done, r.n_trades, r.net_rupees_total, r.folds_positive, num(r.coverage_80_mean, 3), num(r.brier_skill_mean, 3), num(r.sharpe_per_trade, 3)]), [2, 3, 4, 5, 6, 7, 8], { 4: v => v > 0 ? "pos" : "neg" }));
  const row = el("div", null, "row"); const sel = el("select"); for (const r of list.reports) { const o = el("option", r.trial_id); o.value = r.trial_id; sel.append(o); }
  if (trial) sel.value = trial; const go = el("button", "Show details", "button"); go.type = "button"; go.addEventListener("click", () => renderEvaluation(sel.value)); row.append(sel, go); lc.append(row);
  const id = trial || list.reports[list.reports.length - 1].trial_id;
  const rep = await get("/api/evaluation?trial=" + encodeURIComponent(id));
  if (rep.error) { t.append(el("p", rep.error, "muted")); return; }
  const g = el("div", null, "grid"); t.append(g);
  const sm = card("Summary: " + rep.trial_id); g.append(sm);
  const p = rep.pooled || {};
  sm.append(dl([["Sessions", (rep.sessions || []).join(" → ")], ["Rows", rep.rows], ["Label exclusions", JSON.stringify(rep.label_exclusions || {})], ["Unverified days", rep.unverified_days],
    ["Net ₹ (realized, all folds)", rep.net_rupees_total], ["Mean net return per trade", pct(p.mean_net_return)], ["Sharpe per trade", num(p.sharpe_per_trade, 3)], ["PSR vs 0", num(p.psr_vs_zero, 3)], ["MinTRL (95%)", p.min_track_record_95 == null ? "undefined" : Math.ceil(p.min_track_record_95)]]));
  sm.append(el("p", rep.note, "muted"));
  const nf = card("Net ₹ by fold"); g.append(nf);
  nf.append(barChart((rep.net_rupees_by_fold || []).map((v, i) => ({ label: "fold " + (i + 1), value: v })), { fmt: v => v.toFixed(2) }));
  const folds = (rep.folds || []).filter(f => !f.skipped);
  const eq = card("Paper equity by fold (each starts at the policy capital)"); g.append(eq);
  eq.append(lineChart(folds.map((f, i) => ({ name: "fold " + (i + 1), values: f.simulation.equity_curve })), { baseline: (rep.config || {}).W }));
  const cal = card("Calibration and discrimination by fold", "wide"); g.append(cal);
  cal.append(table(["Fold", "Test", "n", "80% cov", "Brier", "BSS", "Pinball q10 (vs uncond.)", "Pinball q50", "Pinball q90", "PIT KS", "Rank IC", "λ", "Trades", "Net ₹", "Hit"],
    folds.map((f, i) => { const m = f.metrics, s = f.simulation; return [i + 1, f.fold.test_start + " → " + f.fold.test_end, m.n, num(m.coverage_80, 3), num(m.brier, 4), num(m.brier_skill, 3), num(m.pinball_0_1, 5) + " (" + num(m["pinball_0_1_unconditional"], 5) + ")", num(m.pinball_0_5, 5), num(m.pinball_0_9, 5), num(m.pit_ks, 3), num(m.rank_ic_mean, 3), f.model.lam, s.n_trades, s.net_rupees_realized, pct(s.hit_rate, 0)]; }), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]));
  const skipped = (rep.folds || []).filter(f => f.skipped); if (skipped.length) cal.append(el("p", skipped.length + " fold(s) skipped: " + skipped.map(f => f.skipped).join(", "), "muted"));
  const tr = card("Last trades (paper, exact charges)", "wide"); g.append(tr);
  const trades = folds.flatMap(f => f.simulation.trades).slice(-50);
  tr.append(trades.length ? table(["Entry", "Exit", "ISIN", "Qty", "Entry px", "Exit px", "Gross", "Cost ₹", "Net ₹", "μ̃ at entry", "q10"], trades.map(x => [x.entry, x.exit, x.isin, x.q, x.entry_price, x.exit_price, pct(x.gross), x.cost.toFixed(2), x.net_pnl, pct(x.mu_shrunk), pct(x.q10)]), [3, 4, 5, 6, 7, 8, 9, 10], { 8: v => v > 0 ? "pos" : "neg" }) : el("p", "No trade passed the gate in any fold (cash was the answer).", "muted"));
  const rj = card("Why candidates were rejected (gate counts across folds)"); g.append(rj);
  const counts = {}; for (const f of folds) for (const [k, v] of Object.entries(f.simulation.rejected || {})) counts[k] = (counts[k] || 0) + v;
  rj.append(Object.keys(counts).length ? barChart(Object.entries(counts).map(([k, v]) => ({ label: k, value: v })), { fmt: v => String(v) }) : el("p", "none", "muted"));
}

// ---- research ------------------------------------------------------------------------------------
async function renderResearch() {
  const t = tab("research"); t.append(el("p", "Loading…", "muted"));
  const r = await get("/api/research"); t.replaceChildren();
  const c = card("Research service"); t.append(c);
  c.append(dl([["Provider", r.provider], ["Queue", Object.keys(r.queue).length ? JSON.stringify(r.queue) : "empty"],
    ["Spent this month", r.usage ? "$" + r.usage.month_usd + " of $" + r.usage.monthly_cap_usd : "unknown"], ["Spent today", r.usage ? "$" + r.usage.day_usd + " of $" + r.usage.daily_cap_usd : "unknown"]]));
  c.append(el("p", "No LLM provider is configured (owner decision). Official NSE feeds are collected directly; the evidence schema, budget ledger and job queue stay ready for a provider adapter if one is ever needed.", "muted"));
}

// ---- controls ------------------------------------------------------------------------------------
async function renderControls() {
  const t = tab("controls"); t.append(el("p", "Loading…", "muted"));
  const [cfg, st, rq] = await Promise.all([get("/api/config"), get("/api/status"), get("/api/requests")]); t.replaceChildren();
  const g = el("div", null, "grid"); t.append(g);
  const an = card("Analysis"); g.append(an);
  const paused = st.service.analysis === "PAUSED";
  const pb = el("button", paused ? "Resume paper analysis" : "Pause paper analysis", "button primary"); pb.type = "button";
  pb.addEventListener("click", async () => { await post("/api/analysis/" + (paused ? "resume" : "pause")); renderControls(); });
  an.append(el("p", "Pausing stops new WAIT/plan records; data collection continues.", "muted"), pb);
  const lg = el("a", "Log in to Kite", "button"); lg.href = "/login/start"; an.append(el("p", "Login opens Zerodha's own page; your password is typed there, never here.", "muted"), lg);
  const pc = card("Policy (bounded; stored in data/private/policy.json)", "wide"); g.append(pc);
  const f = el("form", null, "policy"); const P = cfg.policy, B = cfg.bounds;
  const fields = [["capital", "Capital ₹"], ["K", "Max positions K"], ["cap_fraction", "Per-stock cap (fraction)"], ["reserve_fraction", "Cash reserve (fraction)"], ["v_min_crore", "Min median traded value (₹ crore)"], ["h", "Horizon (sessions)"], ["risk_multiplier", "Risk multiplier (1 = half-Kelly)"]];
  const inputs = {};
  for (const [k, label] of fields) { const l = el("label", label + " [" + B[k][0] + "–" + B[k][1] + "]"); const i = el("input"); i.type = "number"; i.step = "any"; i.value = P[k]; inputs[k] = i; l.append(i); f.append(l); }
  const cl = el("label", "Candidate"); const cs = el("select"); for (const c of ["A", "B", "C"]) { const o = el("option", c); o.value = c; cs.append(o); } cs.value = P.candidate; cl.append(cs); f.append(cl);
  const sl = el("label", "Watchlist symbols (comma-separated; optional)"); const si = el("input"); si.value = (P.symbols || []).join(","); sl.append(si); f.append(sl);
  const fam = el("label", "Families enabled"); const fs = el("div", null, "row"); const famBoxes = {};
  for (const k of ["A", "B", "C"]) { const lab = el("label", k); const cb = el("input"); cb.type = "checkbox"; cb.checked = !!P.families[k]; famBoxes[k] = cb; lab.prepend(cb); fs.append(lab); } fam.append(fs); f.append(fam);
  const save = el("button", "Save policy", "button primary"); save.type = "button"; const msg = el("p", "", "muted");
  save.addEventListener("click", async () => {
    const body = {}; for (const k in inputs) body[k] = Number(inputs[k].value); body.candidate = cs.value;
    body.symbols = si.value.split(",").map(x => x.trim().toUpperCase()).filter(Boolean); body.families = { A: famBoxes.A.checked, B: famBoxes.B.checked, C: famBoxes.C.checked };
    try { await post("/api/config", body); msg.textContent = "Saved."; } catch (e) { msg.textContent = "Refused: " + e.message; }
  });
  pc.append(f, el("div", null, "actions").appendChild(save).parentNode, msg);
  const rc = card("Run a job (executed by the scheduler process, one at a time)", "wide"); g.append(rc);
  const dateIn = el("input"); dateIn.type = "date"; const dl1 = el("label", "Date for file jobs"); dl1.append(dateIn);
  const hIn = el("input"); hIn.type = "number"; hIn.value = P.h; const hl = el("label", "Horizon for evaluate"); hl.append(hIn);
  const jobs = [["prepare", "Prepare today's rule inputs"], ["fetch_public", "Fetch official files for date"], ["build_master", "Build security master for date"], ["panel_build", "Build price panel"], ["decide", "Decide (forecast + plan)"], ["evaluate", "Evaluate (walk-forward)"]];
  const rrow = el("div", null, "row"); rrow.append(dl1, hl);
  for (const [k, label] of jobs) { const b = el("button", label, "button"); b.type = "button"; b.addEventListener("click", async () => {
    const args = {}; if (dateIn.value && (k === "fetch_public" || k === "build_master" || k === "prepare")) args.date = dateIn.value; if (k === "evaluate") { args.candidate = cs.value; args.h = Number(hIn.value); }
    try { await post("/api/request", { kind: k, args }); renderControls(); } catch (e) { alert("Refused: " + e.message); } }); rrow.append(b); }
  rc.append(rrow, el("p", "The scheduler (marketlab run) picks requests up within a minute. If it is not running, requests wait.", "muted"));
  const rl = card("Requests", "wide"); g.append(rl);
  rl.append(rq.requests.length ? table(["Submitted", "Kind", "Args", "State", "Result / error"], rq.requests.map(r => [r.submitted_at, r.kind, JSON.stringify(r.args || {}), r.state, r.error || (r.result == null ? "" : JSON.stringify(r.result).slice(0, 200))]), [], { 3: v => "st-" + v }) : el("p", "none", "muted"));
}

// ---- shell ---------------------------------------------------------------------------------------
let current = "overview";
const renderers = { overview: async () => renderOverview(await get("/api/status")), data: renderData, universe: () => renderUniverse(), forecasts: renderForecasts, evaluation: () => renderEvaluation(), research: renderResearch, controls: renderControls };
async function show(id) {
  current = id; for (const b of $$("#tabs button")) b.classList.toggle("on", b.dataset.tab === id);
  for (const s of $$("main .tab")) s.hidden = s.id !== "tab-" + id;
  try { await renderers[id](); $("#offline").hidden = true; } catch (err) { $("#offline").hidden = false; tab(id).append(el("p", "Could not load: " + err.message, "muted")); }
}
document.addEventListener("DOMContentLoaded", () => {
  for (const b of $$("#tabs button")) b.addEventListener("click", () => show(b.dataset.tab));
  show("overview"); setInterval(() => { if (current === "overview") show("overview"); }, 30000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
});
"""

SERVICE_WORKER = r"""
"use strict";
const SHELL = "marketlab-shell-v2";
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
