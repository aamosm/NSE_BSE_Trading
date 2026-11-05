"""Static assets of the private dashboard (installable PWA). No third-party code, fonts or trackers.

All data is rendered with textContent (never innerHTML), so feed, provider or AI text cannot inject markup. Charts
are inline SVG built from numbers. The service worker caches only the app shell; API, login and callback
responses are never cached, so the page never shows stale account data as if it were current.
"""
from __future__ import annotations

import html
import struct
import zlib
from functools import lru_cache

from .webui import STOCKS_JS, UI_CSS

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
<header class="top">
  <div class="brand"><img src="/icon.svg" alt="" width="30" height="30">
    <div><h1>MarketLab</h1><span class="scope">NSE research and paper decisions · this app cannot place, change or cancel orders</span></div>
    <button id="theme" class="ghost" type="button" title="Theme">Theme: auto</button></div>
  <div class="chips" id="chips"></div>
  <p id="offline" class="banner" hidden>Offline or server unavailable: showing nothing rather than old data.</p>
  <nav id="tabs" aria-label="Sections">
    <button data-tab="stocks" class="on" type="button">Stocks</button>
    <button data-tab="how" type="button">How it works</button>
    <button data-tab="overview" type="button">Overview</button>
    <button data-tab="data" type="button">Data</button>
    <button data-tab="universe" type="button">Universe</button>
    <button data-tab="forecasts" type="button">Decision</button>
    <button data-tab="evaluation" type="button">Evaluation</button>
    <button data-tab="controls" type="button">Controls &amp; AI</button>
  </nav>
</header>
<main>
  <section id="tab-stocks" class="tab"></section>
  <section id="tab-how" class="tab" hidden></section>
  <section id="tab-overview" class="tab" hidden></section>
  <section id="tab-data" class="tab" hidden></section>
  <section id="tab-universe" class="tab" hidden></section>
  <section id="tab-forecasts" class="tab" hidden></section>
  <section id="tab-evaluation" class="tab" hidden></section>
  <section id="tab-controls" class="tab" hidden></section>
</main>
<div id="sheet" class="sheet" hidden><div class="sheet-body" id="sheet-body" role="dialog" aria-modal="true"></div></div>
<div id="tip" class="tip" hidden></div>
<footer>Private service on loopback or your tailnet. Every explanation on this page is assembled from computed numbers by
fixed templates; AI commentary appears only where you ask for it and is labelled.</footer>
</body>
</html>
"""

APP_CSS = UI_CSS

BASE_JS = r"""
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; }
function money(x) { return x == null ? "unknown" : "₹" + (typeof x === "number" ? x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : x); }
function pct(x, d = 2, sign = false) { if (x == null || Number.isNaN(Number(x))) return "unknown"; const v = 100 * Number(x); return (sign && v > 0 ? "+" : "") + v.toFixed(d) + "%"; }
function spct(x, d = 2) { return pct(x, d, true); }
function num(x, d = 4) { return x == null || Number.isNaN(Number(x)) ? "unknown" : Number(x).toFixed(d); }
function crore(x) { return x == null ? "unknown" : "₹" + (x / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 1 }) + " cr"; }
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
function svgText(x, y, text, attrs = {}) { const t = svgEl("text", Object.assign({ x, y }, attrs)); t.textContent = text; return t; }
// ---- tooltip (one shared element; text only) ------------------------------------------------------
function showTip(evt, lines) {
  const t = $("#tip"); if (!t) return; t.replaceChildren(...lines.map((l, i) => el("div", l, i === 0 ? "tip-h" : null))); t.hidden = false;
  const x = (evt.clientX || 0) + 14, y = (evt.clientY || 0) + 14; t.style.left = Math.min(x, (window.innerWidth || 800) - 280) + "px"; t.style.top = y + "px";
}
function hideTip() { const t = $("#tip"); if (t) t.hidden = true; }
function tipOn(node, lines) { node.addEventListener("mousemove", e => showTip(e, lines)); node.addEventListener("mouseleave", hideTip); node.addEventListener("focus", e => showTip(e, lines)); node.addEventListener("blur", hideTip); return node; }
function barChart(items, opts = {}) {
  // items: [{label, value}]; horizontal bars from one baseline, sign by colour and by the printed value
  const W = 600, rowH = 22, H = items.length * rowH + 8, max = Math.max(1e-9, ...items.map(i => Math.abs(i.value || 0)));
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  items.forEach((it, i) => {
    const v = it.value || 0, w = Math.max(1, Math.abs(v) / max * 280), y = i * rowH + 6;
    const r = svgEl("rect", { x: v >= 0 ? 250 : 250 - w, y, width: w, height: 12, rx: 3, class: v >= 0 ? "m-pos" : "m-neg" });
    tipOn(r, [String(it.label), opts.fmt ? opts.fmt(v) : v.toFixed(2)]); s.append(r);
    s.append(svgText(4, y + 10, String(it.label).slice(0, 34), { class: "t-lab" }));
    s.append(svgText(596, y + 10, opts.fmt ? opts.fmt(v) : v.toFixed(2), { "text-anchor": "end", class: "t-val" }));
  });
  s.append(svgEl("line", { x1: 250, y1: 0, x2: 250, y2: H, class: "axis" }));
  return s;
}
function lineChart(series, opts = {}) {
  // series: [{name, values:[y...]}] on a shared x index; legend for two or more series
  const W = 600, H = 170, pad = 34, all = series.flatMap(s => s.values).filter(v => v != null);
  if (!all.length) return el("p", "no data", "muted");
  const lo = Math.min(...all), hi = Math.max(...all), n = Math.max(...series.map(s => s.values.length));
  const sx = x => pad + x / Math.max(1, n - 1) * (W - pad - 8), sy = y => H - 20 + (lo === hi ? 0 : -(y - lo) / (hi - lo) * (H - 34));
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  s.append(svgEl("line", { x1: pad, y1: H - 20, x2: W - 8, y2: H - 20, class: "axis" }));
  series.forEach((sr, k) => {
    const d = sr.values.map((v, i) => v == null ? "" : (i === 0 || sr.values[i - 1] == null ? "M" : "L") + sx(i).toFixed(1) + " " + sy(v).toFixed(1)).join(" ");
    s.append(svgEl("path", { d, fill: "none", class: "ln s" + (k % 4 + 1) }));
  });
  if (opts.baseline != null && opts.baseline >= lo && opts.baseline <= hi) s.append(svgEl("line", { x1: pad, y1: sy(opts.baseline), x2: W - 8, y2: sy(opts.baseline), class: "grid" }));
  s.append(svgText(2, 14, hi.toFixed(0), { class: "t-lab" }), svgText(2, H - 22, lo.toFixed(0), { class: "t-lab" }));
  const w = el("div"); w.append(s);
  if (series.length > 1) { const lg = el("div", null, "legend"); series.forEach((sr, k) => { const it = el("span", null, "lg"); it.append(el("i", null, "sw s" + (k % 4 + 1)), el("span", sr.name)); lg.append(it); }); w.append(lg); }
  return w;
}
function histogram(values, bins = 10) {
  const counts = new Array(bins).fill(0); for (const v of values) { if (v == null) continue; counts[Math.min(bins - 1, Math.max(0, Math.floor(v * bins)))]++; }
  return barChart(counts.map((c, i) => ({ label: (i / bins).toFixed(1) + "-" + ((i + 1) / bins).toFixed(1), value: c })), { fmt: v => String(v) });
}
async function get(path) { const r = await fetch(path, { cache: "no-store", credentials: "same-origin" }); if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || ("HTTP " + r.status)); } return r.json(); }
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "X-MarketLab-Action": "1", "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || ("HTTP " + r.status)); return j;
}
"""

LEGACY_JS = r"""
// ---- overview ------------------------------------------------------------------------------------
const SCHED_TEXT = { ALIVE: "alive", MISSED_HEARTBEATS: "missed heartbeats", NEVER_STARTED: "never started" };
const BROKER_TEXT = { FRESH: "fresh", OVERDUE: "overdue", IDLE_BY_SCHEDULE: "idle by schedule", AUTH_REQUIRED: "login needed", NO_BATCH_YET: "no batch yet", UNKNOWN_CALENDAR: "calendar unknown" };
function when(t) { return t ? String(t).replace("T", " ").slice(0, 16) : "unknown"; }
function sectionLine(sec, fmt) {
  if (!sec || !sec.state || sec.state === "MISSING") return "not in the latest batch (unknown)";
  if (sec.state === "UNAVAILABLE" || sec.state === "MALFORMED") return sec.state.toLowerCase() + " (unknown, not zero)";
  const at = " · received " + when(sec.received_at);
  if (sec.state === "OK") return fmt(sec) + at;
  if (sec.state === "STALE") return "not today's: " + fmt(sec) + at;
  if (sec.state === "SESSION_UNKNOWN") return "session day unknown: " + fmt(sec) + at;
  return sec.state + at;
}
function renderChips(s) {
  const hl = s.health, sc = hl.scheduler, ses = s.session, pd = hl.paper_decisions;
  $("#chips").replaceChildren(chip("Web: reachable", "ok"),
    chip("Scheduler: " + (SCHED_TEXT[sc.status] || sc.status) + (sc.age_seconds != null ? " (" + age(sc.age_seconds) + ")" : ""), sc.status === "ALIVE" ? "ok" : "bad"),
    chip("Market: " + hl.market.status.replaceAll("_", " ").toLowerCase(), "ok"),
    chip("Kite: " + ses.state + (ses.invalidated ? " (invalidated)" : ""), ses.state === "AUTHENTICATED" && !ses.invalidated ? "ok" : "warn"),
    chip("Paper decisions: " + (pd.eligible ? "eligible" : "not eligible"), pd.eligible ? "ok" : "warn"),
    chip("Live orders: none", "ok"),
    chip("Build " + String(s.build.git_head || "unknown").slice(0, 7) + (s.build.source_changed_since_start ? " (files changed since start: restart)" : s.build.package_dirty_paths ? " (uncommitted changes)" : ""), s.build.source_changed_since_start ? "bad" : s.build.package_dirty_paths ? "warn" : "ok"));
}
function renderOverview(s) {
  renderChips(s);
  const hl = s.health, sc = hl.scheduler, ses = s.session, pd = hl.paper_decisions;
  const t = tab("overview"), g = el("div", null, "grid"); t.append(g);
  const h = card("Health (derived now from timestamps)"); g.append(h);
  const cal = s.service.calendar || {};
  h.append(dl([["Scheduler last seen", sc.last_seen ? when(sc.last_seen) + " (" + age(sc.age_seconds) + ")" : "never"],
    ["Scheduler state", sc.reported_state ? sc.reported_state + (sc.reported_state_current ? "" : " (as last reported; not current)") : "never reported"],
    ["Current silence", sc.current_silence_seconds != null ? age(sc.current_silence_seconds) + " without a tick" : "none"],
    ["Last recorded gap", sc.last_recorded_gap ? sc.last_recorded_gap.minutes + " min ending " + when(sc.last_recorded_gap.to) : "none recorded"],
    ["Market session", hl.market.status + " (" + hl.market.day + ")"],
    ["Broker batch", hl.broker.last_batch_at ? when(hl.broker.last_batch_at) + " (" + age(hl.broker.age_seconds) + ")" : "never"],
    ["Broker reads due now", hl.broker.expected_now == null ? "unknown (calendar)" : hl.broker.expected_now ? "yes" : "no"],
    ["Kite session", ses.state === "AUTHENTICATED" ? "valid until " + when(ses.expires_at) : (ses.reason || ses.state)],
    ["Calendar source", (cal.source || "unknown") + (cal.verified_years ? " (verified " + cal.verified_years.join(", ") + ")" : cal.years ? " (" + cal.years.join(", ") + ")" : "")],
    ["Calendar cross-check", !cal.discrepancies_checked ? (cal.cross_check ? cal.cross_check.weekdays_agreeing + " weekdays agree with published files" : "not checked (no NSE holiday-API vintage)") : (cal.discrepancies && Object.keys(cal.discrepancies).length ? "differences in " + Object.keys(cal.discrepancies).join(", ") : "checked: no differences")],
    ["Paper decisions", pd.eligible ? "eligible" : "not eligible: " + pd.reasons.join(", ")]]));
  h.append(el("p", sc.gap_note, "muted"));
  const jobs = Object.entries(s.service.jobs || {});
  if (jobs.length) h.append(el("h3", "Last job results" + (sc.reported_state_current ? "" : " (as last reported)")), table(["Job", "At", "Result"], jobs.map(([k, v]) => [k, when(v.at), v.result + (v.error ? " (" + v.error + ")" : "")])));
  const a = card("Your Zerodha account", "actual"); a.querySelector("h2").prepend(el("span", "ACTUAL", "tag actual-tag")); g.append(a);
  const sec = s.actual.sections || {};
  if (!s.actual.batch) a.append(el("p", "No completed broker collection yet: every account figure is unknown.", "muted"));
  else {
    const hd = sec.holdings || {}, f = sec.funds || {}, p = sec.positions || {}, tr = sec.trades || {};
    a.append(dl([["Batch finished", when(s.actual.batch.finished_at) + " (" + s.actual.batch.status + ")"],
      ["Holdings", sectionLine(hd, x => x.count + " stocks")],
      ["Invested / value", hd.state === "OK" ? money(hd.totals && hd.totals.invested) + " / " + money(hd.totals && hd.totals.value) : "see holdings state"],
      ["Cash", sectionLine(f, x => money(x.cash))],
      ["Cash usable for a decision", hl.actual_cash_usable.ok ? "yes" : "no: " + hl.actual_cash_usable.reasons.join(", ")],
      ["Positions", sectionLine(p, x => x.count + " open")],
      ["Trade book", sectionLine(tr, x => x.fills + " fills" + (x.session_date ? " for " + x.session_date : ""))]]));
    if (hd.rows && hd.rows.length) a.append(table(["Stock", "Qty", "Avg", "Last", "P&L"], hd.rows.map(r => [r.symbol, r.quantity, r.average_price, r.last_price, r.pnl]), [1, 2, 3, 4]));
  }
  const m = s.simulated, sb = card("Paper account", "simulated"); sb.querySelector("h2").prepend(el("span", "SIMULATED", "tag sim-tag")); g.append(sb);
  sb.append(dl([["State", m.state], ["Configured paper capital", money(m.configured_capital)], ["Cash", m.cash == null ? "none (no ledger)" : money(m.cash)],
    ["Positions", m.positions == null ? "none (no ledger)" : m.positions.length], ["P&L", m.pnl == null ? "none (no ledger)" : money(m.pnl)]]), el("p", m.note, "muted"));
  const ld = card("Latest decision"); g.append(ld);
  if (!s.latest_decision) ld.append(el("p", "No decision recorded yet (Controls → Decide, the CLI, or the scheduler's daily check).", "muted"));
  else { const d = s.latest_decision, pol = d.policy || {}; ld.append(dl([["Decision id", d.decision_id], ["Origin", d.origin], ["Session", d.day], ["Action", d.action], ["Reasons", (d.reasons || []).join(", ") || "none"],
    ["Candidate / horizon", (d.candidate || "?") + " / " + (d.h || "?") + " sessions"], ["Policy used", pol.W ? "cap " + money(pol.cap_rupees) + ", K " + pol.K + ", reserve " + money(pol.reserve_rupees) + ", γ " + num(pol.gamma, 6) : "not recorded"],
    ["Promotion", d.promotion_id || "none (WAIT)"], ["Forecasts (diagnostic)", d.forecasts == null ? "none" : d.forecasts], ["Record integrity", d.integrity]])); }
  const dec = card("Decision timeline (same ids as above)", "wide"); g.append(dec);
  if (!s.decisions.length) dec.append(el("p", "No decisions recorded yet.", "muted"));
  for (const x of s.decisions) { const it = el("div", null, "item"); it.append(el("strong", x.action + " · " + x.day + " · " + (x.origin || "legacy") + (x.late_start ? " (late start)" : "")), el("p", x.explanation), el("p", "Id: " + (x.decision_id || "legacy record without id") + " · reasons: " + (x.reasons || []).join(", ") + " · simulated", "muted")); dec.append(it); }
  const e = card("Calendar inputs: corporate actions and listings (not signals)"); g.append(e); const ev = s.events;
  e.append(el("h3", "Ex-dates in the next 14 days"));
  e.append(ev.corporate_actions.length ? table(["Ex-date", "Company", "Purpose"], ev.corporate_actions.map(r => [r.ex_date, r.company, r.purpose])) : el("p", "None in the stored NSE feed.", "muted"));
  e.append(el("h3", "Upcoming listings (next 14 days)"));
  e.append(ev.listings_upcoming.length ? table(["Date", "Symbol", "Series", "Route", "Name"], ev.listings_upcoming.map(r => [r.listing_date, r.symbol, r.series, r.route, r.name])) : el("p", "None in the stored NSE equity list.", "muted"));
  e.append(el("h3", "Recent listings (last 14 days)"));
  e.append(ev.listings_recent.length ? table(["Date", "Symbol", "Series", "Route", "Name"], ev.listings_recent.map(r => [r.listing_date, r.symbol, r.series, r.route, r.name])) : el("p", "None in the stored NSE equity list.", "muted"));
  const b = card("What blocks decisions"); g.append(b);
  for (const x of s.blockers) { const it = el("div", null, "item"); it.append(el("strong", x.code + " · " + (x.basis || "").toLowerCase().replaceAll("_", " ")), el("p", x.text)); b.append(it); }
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

// ---- decision (formerly forecasts) -----------------------------------------------------------------
async function renderForecasts() {
  const t = tab("forecasts"); t.append(el("p", "Loading…", "muted"));
  const r = await get("/api/decision"); t.replaceChildren();
  if (!r.decision) { const c = card("Latest decision"); c.append(el("p", "No decision recorded yet (Controls → Decide). The Stocks tab shows today's research ranking; a paper decision needs a verified promotion.", "muted")); t.append(c); return; }
  const d = r.decision, x = r.diagnostics || {}, g = el("div", null, "grid"); t.append(g);
  const h = card("Decision " + d.decision_id); g.append(h);
  h.append(dl([["Session", d.day], ["Origin", d.origin], ["Action", d.action], ["Reasons", (d.reasons || []).join(", ") || "none"], ["Candidate / horizon", d.candidate + " / " + d.h], ["Generated", when(d.generated_at)],
    ["Universe kept", d.universe ? d.universe.kept : "not reached"], ["Unverified", d.universe && d.universe.unverified.length ? d.universe.unverified.join(", ") : "none"], ["Integrity", d.integrity]]));
  if (d.candidate_spec) h.append(el("p", "Feature builder " + d.candidate_spec.feature_builder + "; columns: " + d.candidate_spec.feature_columns.join(", ") + "; event records used: " + d.candidate_spec.event_records_used, "muted"));
  const pol = d.policy || {}, pc = card("Effective policy used"); g.append(pc);
  pc.append(dl([["Capital", money(pol.W)], ["Per-stock cap", pct(pol.cap_fraction, 0) + " = " + money(pol.cap_rupees)], ["Positions K", pol.K], ["Cash reserve", money(pol.reserve_rupees)], ["Risk aversion γ", num(pol.gamma, 6)], ["Minimum edge / tail limit", pct(pol.min_edge) + " / " + pct(pol.tail_limit)], ["Digest", d.policy_digest]]));
  if (!x.model) { const c = card("Diagnostics"); c.append(el("p", "This decision stopped before any forecast (" + (d.reasons || []).join(", ") + ").", "muted")); g.append(c); return; }
  const m = x.model, mc = card("Model (diagnostic: " + x.plan_status + ")"); g.append(mc);
  const zq = m.z_quantiles || {};
  mc.append(dl([["Target", m.target_id], ["Lambda", m.lam], ["Training rows", m.n_train], ["Training dates", (m.train || []).join(" → ")], ["Calibration residuals", m.calibration_n], ["z quantiles (10/50/90)", [zq["0.1"], zq["0.5"], zq["0.9"]].map(v => num(v, 2)).join(" / ")], ["Bootstrap refits", m.bootstraps]]));
  const pl = card("Hypothetical intents (diagnostic, not a decision)"); g.append(pl);
  const its = x.intents || [];
  pl.append(its.length ? table(["Symbol", "Qty", "Decision close", "Limit", "Cash blocked", "Costs at qty", "Net edge", "P(active > costs)"], its.map(i => [i.symbol || i.isin, i.q, i.decision_close, i.limit, money(i.cash_blocked), pct(i.costs_at_q.cost_fraction), pct(i.costs_at_q.net_edge), num(i.p_active_beats_costs_at_q, 3)]), [1, 2, 3, 4, 5, 6, 7]) : el("p", (x.plan && x.plan.note) || "No position passes the gate at a whole-share quantity.", "muted"));
  const fc = card("Forecasts (gross excess return over the horizon; shrunk mean drives decisions)", "wide"); g.append(fc);
  const rows = (x.forecasts || []).filter(f => f.mu_shrunk != null);
  fc.append(barChart(rows.slice(0, 20).map(f => ({ label: f.symbol || f.isin, value: f.mu_shrunk })), { fmt: v => pct(v) }));
  fc.append(table(["Symbol", "Close", "μ̂", "se", "μ̃ shrunk", "q10", "q50", "q90", "P(excess>0)", "σ̂", "Slippage"],
    rows.map(f => [f.symbol || f.isin, f.close, pct(f.mu_hat), pct(f.se), pct(f.mu_shrunk), pct(f.q10), pct(f.q50), pct(f.q90), num(f.p_positive, 3), pct(f.sigma_hat), pct(f.slippage)]), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]));
}

// ---- evaluation ----------------------------------------------------------------------------------
const CRIT = v => v === true ? "pass" : v === false ? "fail" : "no evidence";
async function renderEvaluation(key) {
  const t = tab("evaluation"); t.append(el("p", "Loading…", "muted"));
  const list = await get("/api/evaluation"); t.replaceChildren();
  const lc = card("Evaluation runs (immutable reports)", "wide"); t.append(lc);
  lc.append(el("p", list.holdout ? "Holdout frozen from " + list.holdout.holdout_start + " (" + when(list.holdout.frozen_at) + "); development runs never read prices from that date on." : "Holdout not frozen yet: evaluations refuse to run until it is (marketlab freeze-holdout, once, after the backfill).", "muted"));
  if (!list.reports.length) { lc.append(el("p", "No evaluation has been run. It needs the historical backfill (about 5.5 years of sessions); see How it works → Validation.", "muted")); return; }
  lc.append(table(["Run", "Kind", "Generated", "Folds", "Trades", "Net ₹", "Folds > 0", "Verdict", "80% cov", "Brier skill"],
    list.reports.map(r => [r.key, r.kind, when(r.generated_at), r.folds_done, r.n_trades, r.net_rupees_total, r.folds_positive, r.verdict || "not computed", num(r.coverage_80, 3), num(r.brier_skill, 3)]), [3, 4, 5, 6, 8, 9], { 5: v => v > 0 ? "pos" : "neg" }));
  const row = el("div", null, "row"); const sel = el("select"); for (const r of list.reports) { const o = el("option", r.key); o.value = r.key; sel.append(o); }
  if (key) sel.value = key; const go = el("button", "Show details", "button"); go.type = "button"; go.addEventListener("click", () => renderEvaluation(sel.value)); row.append(sel, go); lc.append(row);
  const id = key || list.reports[list.reports.length - 1].key;
  const rep = await get("/api/evaluation?trial=" + encodeURIComponent(id));
  if (rep.error) { t.append(el("p", rep.error, "muted")); return; }
  const g = el("div", null, "grid"); t.append(g);
  const sm = card("Summary: " + rep.trial_id + " (" + rep.kind + ")"); g.append(sm);
  const p = rep.pooled || {};
  sm.append(dl([["Sessions", (rep.sessions || []).join(" → ")], ["Data visible until", rep.data_end || "all"], ["Input manifest", (rep.manifest_hash || "").slice(0, 16)],
    ["Opportunities (decision-time)", rep.opportunities], ["Training-eligible rows", rep.rows], ["Missing features", rep.feature_missing],
    ["Net ₹ (NAV at liquidation, all folds)", rep.net_rupees_total], ["Trades closed", rep.n_trades], ["Mean net return per trade", pct(p.mean_net_return)], ["Sharpe per trade", num(p.sharpe_per_trade, 3)]]));
  const pr = rep.promotion, pc = card("Promotion rule (spec 8.6): " + (pr ? pr.verdict : rep.holdout ? "holdout report" : "not computed")); g.append(pc);
  if (pr) { pc.append(table(["Criterion", "Result"], Object.entries(pr.criteria).map(([k, v]) => [k.replaceAll("_", " "), CRIT(v)]), [], { 1: v => v === "pass" ? "pos" : "neg" }));
    pc.append(dl([["DSR", num(pr.dsr, 3)], ["Registered trials", pr.n_trials_registered], ["PBO", pr.pbo && pr.pbo.pbo != null ? num(pr.pbo.pbo, 3) : (pr.pbo && pr.pbo.reason) || "unknown"], ["Verified folds", pr.verified_folds + " of " + pr.folds_done]])); }
  const folds = (rep.folds || []).filter(f => !f.skipped);
  const nf = card("Net ₹ by fold (liquidation NAV − capital)"); g.append(nf);
  nf.append(barChart(folds.map(f => ({ label: f.fold.test_start, value: f.simulation.net_rupees })), { fmt: v => v.toFixed(2) }));
  const eq = card("Daily NAV by fold"); g.append(eq);
  eq.append(lineChart(folds.map((f, i) => ({ name: "fold " + (i + 1), values: f.simulation.nav.map(r => r.nav) })), { baseline: (rep.policy || {}).W }));
  const cal = card("Calibration and discrimination by fold", "wide"); g.append(cal);
  cal.append(table(["Fold", "Test", "Resolved", "80% cov", "Brier", "BSS", "PIT KS", "Rank IC", "λ"],
    folds.map((f, i) => { const m = f.metrics; return [i + 1, f.fold.test_start + " → " + f.fold.test_end, m.n + " / " + m.n_predictions, num(m.coverage_80, 3), num(m.brier, 4), num(m.brier_skill, 3), num(m.pit_ks, 3), num(m.rank_ic_mean, 3), f.model.lam]; }), [2, 3, 4, 5, 6, 7, 8]));
}
"""

CONTROLS_JS = r"""
// ---- controls and AI settings --------------------------------------------------------------------
async function renderControls() {
  const t = tab("controls"); t.append(el("p", "Loading…", "muted"));
  const [cfg, st, rq, ai] = await Promise.all([get("/api/config"), get("/api/status"), get("/api/requests"), get("/api/ai/status")]); t.replaceChildren();
  renderChips(st);
  const g = el("div", null, "grid"); t.append(g);
  const rc = card("Run a job (executed by the scheduler process, one at a time)", "wide"); g.append(rc);
  const dateIn = el("input"); dateIn.type = "date"; const dl1 = el("label", "Date for file jobs"); dl1.append(dateIn);
  const jobs = [["rank", "Rank stocks (research view)"], ["prepare", "Prepare today's rule inputs"], ["fetch_public", "Fetch official files for date"], ["build_master", "Build security master for date"], ["panel_build", "Build price panel"], ["decide", "Decide (saved candidate and horizon)"], ["evaluate", "Evaluate (saved candidate and horizon)"]];
  const rrow = el("div", null, "row"); rrow.append(dl1);
  for (const [k, label] of jobs) { const b = el("button", label, "button" + (k === "rank" ? " primary" : "")); b.type = "button"; b.addEventListener("click", async () => {
    const args = {}; if (dateIn.value && (k === "fetch_public" || k === "build_master" || k === "prepare")) args.date = dateIn.value;
    try { await post("/api/request", { kind: k, args }); renderControls(); } catch (e) { alert("Refused: " + e.message); } }); rrow.append(b); }
  rc.append(rrow, el("p", "The scheduler (marketlab run) picks requests up within a minute; a ranking takes a few minutes. Without the scheduler, run `marketlab rank` in a terminal.", "muted"));
  g.append(aiSettingsCard(ai));
  const an = card("Analysis"); g.append(an);
  const paused = st.service.analysis === "PAUSED";
  const pb = el("button", paused ? "Resume paper analysis" : "Pause paper analysis", "button"); pb.type = "button";
  pb.addEventListener("click", async () => { await post("/api/analysis/" + (paused ? "resume" : "pause")); renderControls(); });
  an.append(el("p", "Pausing stops new decision records; data collection continues.", "muted"), pb);
  const lg = el("a", "Log in to Kite", "button"); lg.href = "/login/start"; an.append(el("p", "Login opens Zerodha's own page; your password is typed there, never here.", "muted"), lg);
  const pc = card("Policy (bounded; stored in the private folder; persisted with every decision and ranking)", "wide"); g.append(pc);
  const f = el("form", null, "policy"); const P = cfg.policy, B = cfg.bounds, E = cfg.policy_effective, N = cfg.nullable || [];
  const fields = [["capital", "Capital ₹"], ["K", "Max positions K"], ["cap_fraction", "Per-stock cap (fraction)"], ["reserve_fraction", "Cash reserve (fraction)"], ["v_min_crore", "Min median traded value (₹ crore)"], ["risk_multiplier", "Risk multiplier (1 = half-Kelly)"]];
  const inputs = {};
  for (const [k, label] of fields) { const l = el("label", label + " [" + B[k][0] + "–" + B[k][1] + "]" + (N.includes(k) ? "; empty = spec default (" + E[k] + ")" : "")); const i = el("input"); i.type = "number"; i.step = "any"; i.value = P[k] == null ? "" : P[k]; inputs[k] = i; l.append(i); f.append(l); }
  const cl = el("label", "Candidate"); const cs = el("select");
  for (const [c, info] of Object.entries(cfg.candidates)) { const o = el("option", c + (info.implemented ? "" : " (not implemented)")); o.value = c; o.disabled = !info.implemented; cs.append(o); } cs.value = P.candidate; cl.append(cs); f.append(cl);
  const hl = el("label", "Horizon (registered for the candidate)"); const hs = el("select");
  const fillH = () => { hs.replaceChildren(); for (const h of cfg.candidates[cs.value].horizons) { const o = el("option", h + " sessions"); o.value = h; hs.append(o); } hs.value = String(P.h); };
  fillH(); cs.addEventListener("change", fillH); hl.append(hs); f.append(hl);
  const save = el("button", "Save policy", "button primary"); save.type = "button"; const msg = el("p", "", "muted");
  save.addEventListener("click", async () => {
    const body = {}; for (const k in inputs) body[k] = inputs[k].value === "" && N.includes(k) ? null : Number(inputs[k].value); body.candidate = cs.value; body.h = Number(hs.value);
    try { await post("/api/config", body); msg.textContent = "Saved. Re-run the ranking to apply it."; renderControls(); } catch (e) { msg.textContent = "Refused: " + e.message; }
  });
  const act = el("div", null, "actions"); act.append(save); pc.append(f, act, msg);
  pc.append(el("h3", "Effective policy (digest " + cfg.policy_digest + ")"),
    dl([["Per-stock cap", money(E.cap_rupees) + " (" + pct(E.cap_fraction, 0) + ")"], ["Positions K", E.K], ["Cash reserve", money(E.reserve_rupees)], ["Risk aversion γ", num(E.gamma, 6)], ["Minimum edge", pct(E.min_edge)], ["Tail limit", pct(E.tail_limit)]]));
  const rl = card("Requests", "wide"); g.append(rl);
  rl.append(rq.requests.length ? table(["Submitted", "Kind", "Args", "State", "Attempt", "Result / error"], rq.requests.map(r => [when(r.submitted_at), r.kind, JSON.stringify(r.args || {}), r.state, r.attempt || 0, r.error || (r.result == null ? "" : JSON.stringify(r.result).slice(0, 200))]), [4], { 3: v => "st-" + v }) : el("p", "none", "muted"));
}
function aiSettingsCard(ai) {
  const c = card("AI explanations (optional, your own Anthropic key)", "wide");
  const k = ai.key || {};
  c.append(el("p", k.set ? "Key: set (" + (k.source === "SESSION" ? "kept in this server's memory until it restarts" : "saved in the private env file") + "). It is never shown again or sent anywhere except Anthropic's API." : "Key: not set. Explanations are off; everything else works without it.", k.set ? "ok-text" : "muted"));
  if (!ai.sdk_installed) c.append(el("p", "The optional Anthropic SDK is not installed: run `pip install anthropic` (or `pip install -e .[ai]`) in this environment.", "warn-text"));
  const kr = el("div", null, "row"); const ki = el("input"); ki.type = "password"; ki.placeholder = "sk-ant-…"; ki.autocomplete = "off"; ki.size = 34;
  const persist = el("select"); for (const [v, lab] of [["0", "Keep for this session only"], ["1", "Save to the private env file"]]) { const o = el("option", lab); o.value = v; persist.append(o); }
  const ks = el("button", "Set key", "button primary"); ks.type = "button"; const kc = el("button", "Remove key", "button"); kc.type = "button"; const km = el("p", "", "muted");
  ks.addEventListener("click", async () => { try { await post("/api/ai/key", { key: ki.value, persist: persist.value === "1" }); ki.value = ""; renderControls(); } catch (e) { km.textContent = "Refused: " + e.message; } });
  kc.addEventListener("click", async () => { try { await post("/api/ai/key", { clear: true }); renderControls(); } catch (e) { km.textContent = "Refused: " + e.message; } });
  kr.append(ki, persist, ks, kc); c.append(kr, km);
  const s = ai.settings || {}, f = el("form", null, "policy");
  const ms = el("select"); for (const [m, info] of Object.entries(ai.models || {})) { const o = el("option", info.label + " · $" + info.price_per_mtok.input + " in / $" + info.price_per_mtok.output + " out per M tokens"); o.value = m; ms.append(o); } ms.value = s.model;
  const ef = el("select"); for (const v of ["low", "medium", "high"]) { const o = el("option", v); o.value = v; ef.append(o); } ef.value = s.effort;
  const mt = el("input"); mt.type = "number"; mt.min = 2000; mt.max = 16000; mt.step = 500; mt.value = s.max_tokens;
  const fb = el("select"); for (const [v, lab] of [["1", "on (a refused request is retried on another model)"], ["0", "off"]]) { const o = el("option", lab); o.value = v; fb.append(o); } fb.value = s.fallback ? "1" : "0";
  for (const [lab, inp] of [["Model", ms], ["Thinking effort", ef], ["Max output tokens (answer + thinking)", mt], ["Server-side fallback", fb]]) { const l = el("label", lab); l.append(inp); f.append(l); }
  const sv = el("button", "Save AI settings", "button"); sv.type = "button"; const sm = el("p", "", "muted");
  sv.addEventListener("click", async () => { try { await post("/api/ai/settings", { model: ms.value, effort: ef.value, max_tokens: Number(mt.value), fallback: fb.value === "1" }); renderControls(); } catch (e) { sm.textContent = "Refused: " + e.message; } });
  const capsF = el("form", null, "policy"), cp = ai.caps || {}, ci = {};
  for (const [kk, lab] of [["monthly_usd", "Monthly cap $ (max $" + cp.hard_monthly_ceiling_usd + ")"], ["daily_usd", "Daily cap $"], ["per_ask_usd", "Per-ask cap $"], ["asks_per_day", "Asks per day"]]) { const l = el("label", lab); const i = el("input"); i.type = "number"; i.step = "any"; i.value = cp[kk]; ci[kk] = i; l.append(i); capsF.append(l); }
  const cs = el("button", "Save spending caps", "button"); cs.type = "button";
  cs.addEventListener("click", async () => { const b = {}; for (const kk in ci) b[kk] = ci[kk].value; try { await post("/api/ai/caps", b); renderControls(); } catch (e) { sm.textContent = "Refused: " + e.message; } });
  const sp = ai.spent || {};
  c.append(el("h3", "Model and output"), f, el("div", null, "actions").appendChild(sv).parentNode, el("h3", "Spending caps (enforced before every call)"), capsF, el("div", null, "actions").appendChild(cs).parentNode, sm,
    dl([["Spent today", "$" + sp.day_usd + " of $" + cp.daily_usd + " (" + sp.asks_today + " asks)"], ["Spent this month", "$" + sp.month_usd + " of $" + cp.monthly_usd], ["Prices verified", (ai.price_source || {}).verified_on + " · " + (ai.price_source || {}).url]]),
    el("p", "Every ask first reserves its worst case (the whole prompt at the cache-write price plus every output token, plus a second attempt if fallback is on) and is refused if that would break a cap; afterwards the actual tokens are charged. The model sees only the stock's card and MarketLab's glossary: no account data.", "muted"));
  return c;
}

// ---- shell ---------------------------------------------------------------------------------------
let current = "stocks";
const renderers = { stocks: () => renderStocks(), how: renderHow, overview: async () => renderOverview(await get("/api/status")), data: renderData, universe: () => renderUniverse(), forecasts: renderForecasts, evaluation: () => renderEvaluation(), controls: renderControls };
async function show(id) {
  current = id; for (const b of $$("#tabs button")) b.classList.toggle("on", b.dataset.tab === id);
  for (const s of $$("main .tab")) s.hidden = s.id !== "tab-" + id;
  try { await renderers[id](); $("#offline").hidden = true; } catch (err) { $("#offline").hidden = false; tab(id).append(el("p", "Could not load: " + err.message, "muted")); }
}
function applyTheme(mode) { const root = document.documentElement; if (mode === "auto") delete root.dataset.theme; else root.dataset.theme = mode; const b = $("#theme"); if (b) b.textContent = "Theme: " + mode; }
document.addEventListener("DOMContentLoaded", () => {
  let mode = "auto"; try { mode = localStorage.getItem("ml-theme") || "auto"; } catch (e) { mode = "auto"; }
  applyTheme(mode);
  const tb = $("#theme"); if (tb) tb.addEventListener("click", () => { mode = mode === "auto" ? "light" : mode === "light" ? "dark" : "auto"; applyTheme(mode); try { localStorage.setItem("ml-theme", mode); } catch (e) { /* private window */ } });
  for (const b of $$("#tabs button")) b.addEventListener("click", () => show(b.dataset.tab));
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });
  const sh = $("#sheet"); if (sh) sh.addEventListener("click", e => { if (e.target === sh) closeSheet(); });
  get("/api/status").then(renderChips).catch(() => {});
  show("stocks"); setInterval(() => { if (current === "overview") show("overview"); }, 30000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
});
"""

APP_JS = BASE_JS + LEGACY_JS + STOCKS_JS + CONTROLS_JS

SERVICE_WORKER = r"""
"use strict";
const SHELL = "marketlab-shell-v4";
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
