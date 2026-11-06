"""Dashboard styles and the research views: Stocks (the ranking and one stock's card), How it works, and the AI panel.

Rendering rules (same as the rest of the dashboard): text is set with textContent only, charts are SVG built from
numbers already computed by the server, and colour is never the only carrier of meaning (every class badge has an
icon and a word, every chart value is printed or in a tooltip and a table).
"""

UI_CSS = r"""
:root{color-scheme:light;--bg:#f4f5f7;--card:#ffffff;--chart:#fcfcfb;--ink:#101418;--ink2:#4a5561;--muted:#6f7a86;
--line:#e3e6ea;--line2:#cfd4da;--accent:#2a78d6;--accent-ink:#ffffff;--btn:#eef1f4;--hover:#f2f6fb;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--pos:#2a78d6;--neg:#e34948;--band:rgba(42,120,214,.13);
--good:#0ca30c;--good-text:#006300;--warn:#fab219;--warn-text:#8a5a00;--serious:#ec835a;--bad:#d03b3b;--bad-text:#b42318;
--actual:#1d4ed8;--sim:#7c3aed;--shadow:0 1px 2px rgba(16,20,24,.06),0 4px 16px rgba(16,20,24,.06)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#0d0f12;--card:#16191d;
--chart:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a9a92;--line:#2a2e33;--line2:#3a3f45;--accent:#3987e5;--accent-ink:#0d0f12;
--btn:#21262c;--hover:#1d232a;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--pos:#3987e5;--neg:#e66767;
--band:rgba(57,135,229,.18);--good-text:#3fd13f;--warn-text:#fab219;--bad-text:#f87171;--actual:#60a5fa;--sim:#c4b5fd;
--shadow:0 1px 2px rgba(0,0,0,.4)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0f12;--card:#16191d;--chart:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#9a9a92;--line:#2a2e33;--line2:#3a3f45;--accent:#3987e5;--accent-ink:#0d0f12;--btn:#21262c;--hover:#1d232a;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--pos:#3987e5;--neg:#e66767;--band:rgba(57,135,229,.18);
--good-text:#3fd13f;--warn-text:#fab219;--bad-text:#f87171;--actual:#60a5fa;--sim:#c4b5fd;--shadow:0 1px 2px rgba(0,0,0,.4)}
*{box-sizing:border-box}
html,body{background:var(--bg)}
body{margin:0;color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:max(12px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom))}
header.top,main,footer{max-width:1240px;margin:0 auto}
.brand{display:flex;align-items:center;gap:12px}.brand>div{flex:1;min-width:0}h1{font-size:21px;margin:0;letter-spacing:-.01em}
.scope,.hint,footer,.muted{color:var(--muted);font-size:13px}.ok-text{color:var(--good-text)}.warn-text{color:var(--warn-text)}
h2{font-size:16px;margin:0 0 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h3{font-size:13px;margin:14px 0 6px;color:var(--ink2);text-transform:uppercase;letter-spacing:.05em}
h4{font-size:15px;margin:14px 0 4px}h5{font-size:14px;margin:10px 0 2px;color:var(--ink2)}
nav#tabs{display:flex;gap:4px;overflow-x:auto;padding:10px 0 0;border-bottom:1px solid var(--line);margin-bottom:14px}
nav#tabs button{flex:0 0 auto;border:0;background:none;color:var(--ink2);font:inherit;font-weight:600;padding:8px 12px;
cursor:pointer;border-bottom:2px solid transparent}nav#tabs button.on{color:var(--ink);border-bottom-color:var(--accent)}
nav#tabs button:hover{color:var(--ink)}
.ghost{border:1px solid var(--line);background:none;color:var(--ink2);font:inherit;font-size:13px;border-radius:8px;padding:5px 10px;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:0 0 14px;box-shadow:var(--shadow);min-width:0}
.card.wide{grid-column:1/-1}.actual{border-left:5px solid var(--actual)}.simulated{border-left:5px solid var(--sim)}
.tag{font-size:11px;font-weight:700;letter-spacing:.06em;padding:2px 8px;border-radius:999px;color:#fff}
.actual-tag{background:var(--actual)}.sim-tag{background:var(--sim)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 0}
.chip{font-size:12px;font-weight:600;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:3px 10px;white-space:nowrap}
.chip.ok{color:var(--good-text)}.chip.warn{color:var(--warn-text)}.chip.bad{color:var(--bad-text)}
.banner{background:var(--warn);color:#000;padding:8px 12px;border-radius:10px}
.notice{border:1px solid var(--line2);border-left:5px solid var(--warn);background:var(--card);border-radius:12px;padding:12px 14px;margin:0 0 14px}
.notice.bad{border-left-color:var(--bad)}.notice strong{display:block;margin-bottom:2px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
.button{appearance:none;border:1px solid var(--line2);background:var(--btn);color:var(--ink);font:inherit;font-weight:600;
border-radius:10px;padding:8px 12px;text-decoration:none;min-height:40px;display:inline-flex;align-items:center;cursor:pointer}
.button:hover{border-color:var(--accent)}.button.primary{background:var(--accent);color:var(--accent-ink);border-color:transparent}
.button.small{min-height:32px;padding:4px 10px;font-size:13px}.button[disabled]{opacity:.5;cursor:default}
dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;margin:0}dt{color:var(--muted)}
dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.table{width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th{position:sticky;top:0;background:var(--card);color:var(--ink2);font-weight:600;font-size:12px;z-index:1}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}td.wrap{white-space:normal;min-width:220px;color:var(--ink2)}
tr.click{cursor:pointer}tr.click:hover,tr.click:focus{background:var(--hover);outline:none}
.item{border-top:1px solid var(--line);padding:8px 0}.item:first-child{border-top:0}
.st-QUEUED,.st-RUNNING{color:var(--warn-text)}.st-FAILED,.st-INTERRUPTED{color:var(--bad-text)}.st-DONE{color:var(--good-text)}
.pos{color:var(--good-text)}.neg{color:var(--bad-text)}
form.policy{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
form.policy label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:3px}
input,select,textarea{font:inherit;padding:7px 9px;border:1px solid var(--line2);border-radius:8px;background:var(--card);color:var(--ink);min-height:38px}
textarea{width:100%;min-height:72px;resize:vertical}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
footer{margin-top:24px;padding-top:12px;border-top:1px solid var(--line)}
/* charts */
svg.chart{width:100%;height:auto;display:block;margin:6px 0;overflow:visible}
svg text{font-size:11px}.t-lab{fill:var(--muted)}.t-val{fill:var(--ink2);font-variant-numeric:tabular-nums}.t-ink{fill:var(--ink)}
.t-strong{fill:var(--ink);font-weight:600}.axis{stroke:var(--line2);stroke-width:1}.grid{stroke:var(--line);stroke-width:1}
.m-pos{fill:var(--pos)}.m-neg{fill:var(--neg)}.band{fill:var(--band)}.th-line{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:3 3}
.zero{stroke:var(--ink);stroke-width:1;opacity:.55}.dot{fill:var(--accent);stroke:var(--chart);stroke-width:2}
.dot-raw{fill:var(--chart);stroke:var(--accent);stroke-width:2}.q50{stroke:var(--accent);stroke-width:2}
.ln{stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.ln.s1{stroke:var(--s1)}.ln.s2{stroke:var(--s2)}.ln.s3{stroke:var(--s3)}.ln.s4{stroke:var(--s4)}
.f1{fill:var(--s1)}.f2{fill:var(--s2)}.f3{fill:var(--s3)}.f4{fill:var(--s4)}.t-in{fill:#fff;font-weight:600}.t-in.dark{fill:#0b0b0b}
.cross{stroke:var(--line2);stroke-width:1}.mark-act{fill:var(--s3)}.mark-bad{fill:var(--neg)}.hit{fill:transparent;cursor:crosshair}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-top:4px}
.lg{display:inline-flex;align-items:center;gap:6px}.sw{display:inline-block;width:12px;height:12px;border-radius:3px}
.sw.s1{background:var(--s1)}.sw.s2{background:var(--s2)}.sw.s3{background:var(--s3)}.sw.s4{background:var(--s4)}
.tip{position:fixed;z-index:50;max-width:280px;background:var(--card);color:var(--ink);border:1px solid var(--line2);
border-radius:8px;padding:7px 9px;font-size:12px;box-shadow:var(--shadow);pointer-events:none}.tip-h{font-weight:600;margin-bottom:2px}
/* classes */
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;border-radius:999px;padding:3px 10px;
border:1px solid var(--line2);white-space:nowrap}.badge .ic{font-size:11px}
.cls-BUY_CANDIDATE{background:rgba(12,163,12,.14);color:var(--good-text);border-color:rgba(12,163,12,.45)}
.cls-QUALIFIES{background:rgba(12,163,12,.07);color:var(--good-text)}
.cls-HOLD_OFF{background:var(--btn);color:var(--ink2)}
.cls-HIGH_RISK{background:rgba(250,178,25,.16);color:var(--warn-text);border-color:rgba(250,178,25,.55)}
.cls-AVOID{background:rgba(208,59,59,.12);color:var(--bad-text);border-color:rgba(208,59,59,.45)}
.cls-NO_FORECAST,.cls-INELIGIBLE{background:none;color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:0 0 14px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;cursor:pointer;text-align:left;font:inherit;color:var(--ink)}
.tile.off{opacity:.45}.tile .v{font-size:26px;font-weight:650;line-height:1.1;display:block;margin-top:4px}
.tile .d{font-size:12px;color:var(--muted);display:block}
.hero h2{font-size:20px;margin-bottom:4px}.hero{margin:4px 0 14px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px}.toolbar input[type=search]{flex:1;min-width:200px}
.seg{display:flex;width:100%;height:28px;border-radius:6px;overflow:hidden;gap:2px;background:var(--chart);margin:6px 0}
.seg span{display:block;height:100%;min-width:2px}
.sym{font-weight:700}.nm{display:block;font-size:11px;color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis}
@media (max-width:760px){.opt{display:none}td.wrap{min-width:160px}}
/* sheet (one stock) */
.sheet{position:fixed;inset:0;z-index:40;background:rgba(10,12,14,.45);display:flex;justify-content:flex-end}
.sheet[hidden]{display:none}.sheet-body{background:var(--bg);width:min(1060px,100%);height:100%;overflow-y:auto;padding:16px 18px 40px;
box-shadow:-8px 0 30px rgba(0,0,0,.25)}
.sheet-head{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:12px}.sheet-head .grow{flex:1;min-width:220px}
.sheet-head h2{font-size:22px;margin:0}.lead{font-size:16px;line-height:1.55;margin:6px 0 0}
.insight{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:10px 12px;margin:8px 0;background:var(--card)}
.insight.UNVALIDATED_MODEL,.insight.SURVEILLANCE_UNKNOWN{border-left-color:var(--warn)}.insight strong{display:block}
.term{display:inline-block;font-size:11px;border:1px dashed var(--line2);border-radius:6px;padding:0 6px;margin:4px 4px 0 0;color:var(--ink2);cursor:help}
ol.steps{padding-left:20px;margin:0}ol.steps li{margin:0 0 12px}ol.steps li strong{display:block}
.check{display:grid;grid-template-columns:22px 1fr auto;gap:6px;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}
.check .ok{color:var(--good-text)}.check .no{color:var(--bad-text)}.check .unk{color:var(--warn-text)}
.ai-answer{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-top:10px}
.ai-answer ul,.ai-answer ol{padding-left:22px}.ai-label{font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--sim);text-transform:uppercase}
.presets{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
details{border-top:1px solid var(--line);padding:8px 0}summary{cursor:pointer;font-weight:600}
code,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
pre.maths{white-space:pre-wrap;background:var(--chart);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:6px 0;font-size:12px}
.stage{display:grid;grid-template-columns:34px 1fr;gap:10px;padding:12px 0;border-top:1px solid var(--line)}
.stage .no{width:30px;height:30px;border-radius:50%;background:var(--accent);color:var(--accent-ink);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}
.pill{display:inline-block;font-size:12px;background:var(--btn);border:1px solid var(--line);border-radius:8px;padding:3px 8px;margin-top:6px;color:var(--ink2)}
.gl{padding:8px 0;border-top:1px solid var(--line)}.gl strong{display:block}
"""

STOCKS_JS = r"""
// ---- research ranking: the Stocks tab --------------------------------------------------------------
const CLASS_ORDER = ["BUY_CANDIDATE", "QUALIFIES", "HOLD_OFF", "HIGH_RISK", "AVOID", "NO_FORECAST", "INELIGIBLE"];
const CLASS_ICON = { BUY_CANDIDATE: "▲", QUALIFIES: "●", HOLD_OFF: "○", HIGH_RISK: "!", AVOID: "✕", NO_FORECAST: "?", INELIGIBLE: "–" };
const CLASS_FILL = { BUY_CANDIDATE: "var(--good)", QUALIFIES: "var(--s3)", HOLD_OFF: "var(--line2)", HIGH_RISK: "var(--warn)", AVOID: "var(--bad)", NO_FORECAST: "var(--muted)", INELIGIBLE: "var(--line)" };
let STOCKS = null, CLASSES = {};
const SV = { show: new Set(["BUY_CANDIDATE", "QUALIFIES", "HOLD_OFF", "HIGH_RISK", "AVOID", "NO_FORECAST"]), q: "", sort: "rank", limit: 150, capital: null };
function classTitle(c) { return (CLASSES[c] && CLASSES[c].title) || c; }
function badge(c) { const b = el("span", null, "badge cls-" + c); b.append(el("span", CLASS_ICON[c] || "", "ic"), el("span", classTitle(c))); return b; }
const SORTS = {
  rank: ["Best net edge first", (a, b) => (a.rank || 1e9) - (b.rank || 1e9)],
  forecast: ["Highest forecast", (a, b) => (b.mu_shrunk ?? -9) - (a.mu_shrunk ?? -9)],
  worst: ["Lowest forecast (avoid first)", (a, b) => (a.mu_shrunk ?? 9) - (b.mu_shrunk ?? 9)],
  pbeat: ["Highest P(beat index)", (a, b) => (b.p_positive ?? -1) - (a.p_positive ?? -1)],
  cost: ["Lowest cost", (a, b) => (a.cost ?? 9) - (b.cost ?? 9)],
  vol: ["Calmest (lowest volatility)", (a, b) => (a.vol_20 ?? 9) - (b.vol_20 ?? 9)],
  mom: ["Strongest 12-1 momentum", (a, b) => (b.mom_12_1 ?? -9) - (a.mom_12_1 ?? -9)],
  liq: ["Most traded", (a, b) => (b.median_value_20 ?? -1) - (a.median_value_20 ?? -1)],
  symbol: ["Symbol A-Z", (a, b) => String(a.symbol).localeCompare(String(b.symbol))],
};
function capitalBar(r) {
  // Read the same day at another capital: the server restates costs, gates and calls from the stored forecasts.
  const c = card("Capital used for these calls"), row = el("div", null, "toolbar");
  const inp = el("input"); inp.type = "number"; inp.min = "1000"; inp.max = "100000000"; inp.step = "1000";
  inp.value = String(Math.round((r.policy || {}).W || 10000)); inp.setAttribute("aria-label", "Capital in rupees");
  const go = el("button", "Apply", "button small primary"); go.type = "button";
  const apply = async () => {
    const w = Number(inp.value);
    if (!(w >= 1000 && w <= 100000000)) { alert("Capital must be between ₹1,000 and ₹10,00,00,000."); return; }
    go.disabled = true; go.textContent = "Recomputing…";
    SV.capital = w; STOCKS = await get("/api/stocks?capital=" + encodeURIComponent(w)); renderStocks();
  };
  go.addEventListener("click", apply);
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
  row.append(inp, go);
  for (const w of [3000, 10000, 30000, 100000]) {
    const b = el("button", money(w), "button small"); b.type = "button";
    b.addEventListener("click", () => { inp.value = String(w); apply(); });
    row.append(b);
  }
  c.append(row);
  const re = r.restated;
  if (re) {
    c.append(el("p", "Restated from the " + money(re.from_capital) + " ranking of " + re.from_day + ": quantities, exact charges, gates and calls recomputed at " + money(re.capital) + ". The model was not refitted and the forecasts are unchanged.", "muted"));
    const notes = [];
    if (re.priced_out) notes.push(re.priced_out + " stocks no longer fit (one share costs more than half this capital)");
    if (re.newly_eligible_needs_run) notes.push(re.newly_eligible_needs_run + " stocks would now be eligible but carry no forecast in this file — run `marketlab rank --capital " + Math.round(re.capital) + "` to rank them");
    notes.push("selection here is greedy by net edge, not the correlation-aware allocator");
    const ul = el("ul"); for (const x of notes) ul.append(el("li", x)); c.append(ul);
  } else {
    c.append(el("p", "These calls were computed at " + money((r.policy || {}).W) + ", the capital saved in Controls. Change it above to see the same day at another amount — only costs, whole-share quantities and the gates move, never the forecast.", "muted"));
  }
  return c;
}
function topTen(r, pol) {
  // Items x attributes of different kinds -> a table (the forecast itself is charted per stock in the sheet).
  const c = card("Today's top 10 by expected return (unvalidated)");
  const ranked = STOCKS.stocks.filter(s => s.rank).sort((a, b) => a.rank - b.rank).slice(0, 10);
  if (!ranked.length) { c.append(el("p", "No stock has a forecast today, so there is nothing to rank.", "muted")); return c; }
  c.append(el("p", "The model's own order, best expected return first, out of " + (ranked[0].rank_of || 0) + " stocks with a forecast. The call in the second column is what the gates make of it: a stock can top this list and still be one you should not buy. Figures are returns against the Nifty 50 over " + r.h + " sessions, at " + money(pol.cap_rupees) + " per position.", "muted"));
  const w = el("div", null, "table"), tb = el("table"), hr = el("tr");
  for (const [h, cl] of [["#", "n"], ["Stock", ""], ["Call", ""], ["Forecast μ̃", "n"], ["₹ vs index (10–90%)", "n"], ["Shares", "n opt"], ["Cost", "n"], ["Gap to buy gate", "n"]]) hr.append(el("th", h, cl || null));
  tb.append(hr);
  for (const s of ranked) {
    const tr = el("tr", null, "click"); tr.tabIndex = 0;
    const sc = el("td"); sc.append(el("span", s.symbol, "sym"), el("span", s.name || "", "nm"));
    const cc = el("td"); cc.append(badge(s.class));
    const v = s.position || 0;
    const lo = (s.q10 != null && s.cost != null) ? v * (s.q10 - s.cost) : null, hi = (s.q90 != null && s.cost != null) ? v * (s.q90 - s.cost) : null;
    const rng = el("td", lo == null ? "—" : money(Math.round(lo)) + " to " + money(Math.round(hi)), "n");
    if (lo != null) tipOn(rng, ["Net of all costs, against the Nifty 50", "8 of 10 months land in this band", "A worse month than the low figure happens 1 time in 10"]);
    const gap = (s.net_edge != null && s.threshold != null) ? s.net_edge - pol.min_edge : null;
    const gc = el("td", gap == null ? "—" : pct(gap), "n " + (gap != null && gap >= 0 ? "good" : "bad"));
    if (gap != null) tipOn(gc, ["How far the net edge is from the minimum edge of " + pct(pol.min_edge), gap >= 0 ? "Clears the edge gate" : "Short by " + pct(-gap) + " — the cost of trading is larger than the expected gain"]);
    tr.append(el("td", s.rank, "n"), sc, cc, el("td", s.mu_shrunk == null ? "—" : pct(s.mu_shrunk), "n"), rng,
      el("td", s.q == null ? "—" : s.q, "n opt"), el("td", s.cost == null ? "—" : pct(s.cost), "n"), gc);
    tr.addEventListener("click", () => openStock(s.isin));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openStock(s.isin); });
    tb.append(tr);
  }
  w.append(tb); c.append(w);
  c.append(el("p", "Click a row for the full working. These are not recommendations: the model behind them is unvalidated, and on most days no stock clears the gates.", "muted"));
  return c;
}
async function renderStocks(force) {
  const t = tab("stocks");
  if (!STOCKS || force) { t.append(el("p", "Loading the ranking…", "muted")); STOCKS = await get("/api/stocks" + (SV.capital ? "?capital=" + encodeURIComponent(SV.capital) : "")); t.replaceChildren(); }
  const d = STOCKS; CLASSES = d.classes || {};
  if (!d.ranking) {
    const c = card("No ranking yet"); c.append(el("p", d.hint || "Run the ranking first.", "muted"));
    const b = el("button", "Queue a ranking job", "button primary"); b.type = "button";
    b.addEventListener("click", async () => { try { await post("/api/request", { kind: "rank", args: {} }); b.textContent = "Queued: the scheduler runs it within a minute (or run `marketlab rank`)"; b.disabled = true; } catch (e) { alert("Refused: " + e.message); } });
    c.append(b); t.append(c); return;
  }
  const r = d.ranking, pol = r.policy || {}, v = r.validation || {};
  const hero = el("section", null, "hero");
  hero.append(el("h2", "What the research ranking says after the close of " + r.day),
    el("p", "Next session " + (r.entry_session || "unknown") + " · horizon " + r.h + " sessions (about a month) · paper capital " + money(pol.W) + ": at most " + pol.K + " positions of up to " + money(pol.cap_rupees) + " each, " + money(pol.reserve_rupees) + " kept in cash.", "muted"));
  t.append(hero);
  if (r.integrity && r.integrity !== "OK") { const n = el("div", null, "notice bad"); n.append(el("strong", "Ranking file failed its integrity check (" + r.integrity + ")"), el("span", "Do not rely on it; re-run the ranking.")); t.append(n); }
  if (v.status !== "PROMOTED") {
    const n = el("div", null, "notice"); n.append(el("strong", "Unvalidated research view: not a recommendation"),
      el("span", "The model behind these calls has not passed walk-forward testing (" + v.sessions_available + " sessions of history available; the registered evaluation needs " + v.sessions_needed_for_registered_evaluation + "). Treat each call as a structured, fully explained screen and check the reasons yourself. Paper decisions stay off until a model is promoted."));
    t.append(n);
  }
  if (r.status !== "RANKED") { const n = el("div", null, "notice bad"); n.append(el("strong", "No forecasts today: " + r.status), el("span", "Only eligibility is shown.")); t.append(n); }
  if (d.summary && d.summary.length) { const sc = card("Today in plain words"); const ul = el("ul"); for (const x of d.summary) ul.append(el("li", x)); sc.append(ul); t.append(sc); }
  t.append(capitalBar(r));
  t.append(topTen(r, pol));
  const tiles = el("div", null, "tiles");
  for (const c of CLASS_ORDER) {
    const b = el("button", null, "tile" + (SV.show.has(c) ? "" : " off")); b.type = "button";
    const top = el("span"); top.append(badge(c)); b.append(top, el("span", (r.counts || {})[c] || 0, "v"), el("span", (CLASSES[c] || {}).rule || "", "d"));
    b.addEventListener("click", () => { if (SV.show.has(c)) SV.show.delete(c); else SV.show.add(c); SV.limit = 150; renderStocks(); });
    tiles.append(b);
  }
  t.append(tiles);
  const total = CLASS_ORDER.reduce((s, c) => s + ((r.counts || {})[c] || 0), 0), seg = el("div", null, "seg");
  for (const c of CLASS_ORDER) { const n = (r.counts || {})[c] || 0; if (!n) continue; const p = el("span"); p.style.width = (100 * n / total) + "%"; p.style.background = CLASS_FILL[c]; tipOn(p, [classTitle(c), n + " stocks (" + (100 * n / total).toFixed(1) + "%)"]); seg.append(p); }
  t.append(seg, el("p", "Share of today's " + total + " stocks by call (hover for counts). Click a tile above to show or hide that call.", "muted"));
  const bar = el("div", null, "toolbar"), q = el("input"); q.type = "search"; q.placeholder = "Search symbol or company…"; q.value = SV.q;
  const so = el("select"); for (const [k, [lab]] of Object.entries(SORTS)) { const o = el("option", lab); o.value = k; so.append(o); } so.value = SV.sort;
  const re = el("button", "Reload", "button small"); re.type = "button"; re.addEventListener("click", () => renderStocks(true));
  bar.append(q, so, re); t.append(bar);
  const holder = el("div"); t.append(holder);
  q.addEventListener("input", () => { SV.q = q.value; SV.limit = 150; drawStockTable(holder); });
  so.addEventListener("change", () => { SV.sort = so.value; drawStockTable(holder); });
  drawStockTable(holder);
  const meta = card("Where these numbers come from"); t.append(meta);
  const m = r.model || {};
  meta.append(dl([["Model", (m.target_id || "none") + (m.lam != null ? " · ridge λ = " + m.lam : "")], ["Training", m.train ? m.train.join(" → ") + " (" + m.train_rows + " rows)" : "not trained"],
    ["Calibration", m.calibration ? m.calibration.join(" → ") + " (" + m.calibration_n + " residuals)" : "none"], ["Universe", (r.universe || {}).kept + " stocks kept; unverified: " + (((r.universe || {}).unverified || []).join(", ") || "nothing")],
    ["Price history", (r.data || {}).panel_first + " → " + (r.data || {}).panel_last + " (" + (r.data || {}).stored_sessions + " sessions)"], ["Corporate actions", (r.data || {}).actions ? (r.data.actions.mapped + " listed actions mapped") : "registry not loaded"],
    ["Rule files", ((r.data || {}).rule_inputs || {}).availability + (((r.data || {}).rule_inputs || {}).have_surveillance_file ? " (surveillance file used)" : " (surveillance unknown)")],
    ["Forward evidence", (r.forward || {}).eligible ? "yes: recorded before the next session opened" : "no (" + ((r.forward || {}).why || "unknown") + ")"],
    ["Ranking file", String(r.digest || "").slice(0, 16) + " · created " + String(r.created_at || "").replace("T", " ").slice(0, 16)]]));
  meta.append(el("p", "How it works explains every step in plain language.", "muted"));
}
function drawStockTable(holder) {
  holder.replaceChildren();
  const ql = SV.q.trim().toLowerCase();
  let rows = STOCKS.stocks.filter(s => SV.show.has(s.class) && (!ql || String(s.symbol).toLowerCase().includes(ql) || String(s.name || "").toLowerCase().includes(ql)));
  rows.sort(SORTS[SV.sort][1]);
  const n = rows.length; rows = rows.slice(0, SV.limit);
  const w = el("div", null, "table"), tb = el("table"), hr = el("tr");
  const heads = [["#", "n"], ["Stock", ""], ["Call", ""], ["Forecast", "n"], ["Range (10–90%)", "opt"], ["Cost", "n opt"], ["Net edge", "n"], ["P(beat)", "n opt"], ["Close", "n opt"], ["Why", "opt"]];
  for (const [h, c] of heads) hr.append(el("th", h, c || null));
  tb.append(hr);
  for (const s of rows) {
    const tr = el("tr", null, "click"); tr.tabIndex = 0;
    const sc = el("td"); sc.append(el("span", s.symbol, "sym"), el("span", s.name || "", "nm"));
    const cc = el("td"); cc.append(badge(s.class));
    const rc = el("td", null, "opt"); rc.append(miniRange(s));
    tr.append(el("td", s.rank || "", "n"), sc, cc, el("td", s.mu_shrunk == null ? "–" : spct(s.mu_shrunk), "n"), rc, el("td", s.cost == null ? "–" : pct(s.cost), "n opt"),
      el("td", s.net_edge == null ? "–" : spct(s.net_edge), "n " + (s.net_edge > 0 ? "pos" : "")), el("td", s.p_positive == null ? "–" : (100 * s.p_positive).toFixed(0) + "%", "n opt"),
      el("td", money(s.close), "n opt"), el("td", s.headline, "wrap opt"));
    tr.addEventListener("click", () => openStock(s.isin)); tr.addEventListener("keydown", e => { if (e.key === "Enter") openStock(s.isin); });
    tb.append(tr);
  }
  w.append(tb); holder.append(w);
  holder.append(el("p", "Showing " + rows.length + " of " + n + " stocks. Forecast = shrunk expected return versus the Nifty 50 over the horizon, before costs. Net edge = forecast minus the round-trip cost at the quantity your cap allows.", "muted"));
  if (n > rows.length) { const more = el("button", "Show 150 more", "button small"); more.type = "button"; more.addEventListener("click", () => { SV.limit += 150; drawStockTable(holder); }); holder.append(more); }
}
function miniRange(s) {
  const W = 130, H = 16, lo = -0.2, hi = 0.2, x = v => 4 + (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (W - 8);
  const g = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
  if (s.q10 == null || s.q90 == null) { g.append(svgEl("line", { x1: 4, y1: 8, x2: W - 4, y2: 8, class: "grid" })); return g; }
  g.append(svgEl("rect", { x: x(s.q10), y: 4, width: Math.max(1, x(s.q90) - x(s.q10)), height: 8, rx: 4, class: "band" }));
  g.append(svgEl("line", { x1: x(0), y1: 1, x2: x(0), y2: 15, class: "zero" }));
  g.append(svgEl("circle", { cx: x(s.mu_shrunk || 0), cy: 8, r: 3.5, class: "dot" }));
  tipOn(g, [s.symbol + ": 80% range", spct(s.q10) + " to " + spct(s.q90) + " (shrunk forecast " + spct(s.mu_shrunk) + ")"]);
  return g;
}

// ---- one stock -------------------------------------------------------------------------------------
function closeSheet() { const s = $("#sheet"); if (s) s.hidden = true; hideTip(); }
async function openStock(isin) {
  const sh = $("#sheet"), body = $("#sheet-body"); sh.hidden = false; body.replaceChildren(el("p", "Loading…", "muted"));
  let d;
  try {
    if (!HOW) HOW = await get("/api/how").catch(() => null);  // feature names and the glossary for tooltips
    d = await get("/api/stock?isin=" + encodeURIComponent(isin));
  } catch (e) { body.replaceChildren(el("p", "Could not load: " + e.message, "muted")); return; }
  if (d.error) { body.replaceChildren(el("p", d.error, "muted")); return; }
  renderStockSheet(body, d);
}
function renderStockSheet(body, d) {
  body.replaceChildren();
  const c = d.card, fc = c.forecast, costs = c.costs, rk = d.ranking || {};
  const head = el("div", null, "sheet-head"), g1 = el("div", null, "grow");
  const h = el("h2"); h.append(el("span", c.symbol), badge(c.class)); g1.append(h, el("div", (c.name || "") + " · " + c.isin + " · close " + money(c.close) + " (" + spct(c.day_change) + " today)" + (c.rank ? " · rank " + c.rank + " of " + c.rank_of : ""), "muted"));
  const x = el("button", "Close", "button small"); x.type = "button"; x.addEventListener("click", closeSheet);
  head.append(g1, x); body.append(head);
  const lead = d.narrative[0]; body.append(el("p", lead ? lead.text : "", "lead"));
  if ((rk.validation || {}).status !== "PROMOTED") body.append(el("p", "Research view from an unvalidated model (after the close of " + rk.day + "). Not a recommendation.", "muted"));
  const charts = el("div", null, "grid2"); body.append(charts);
  if (fc) {
    const c1 = card("Forecast range vs what a buy needs"); c1.append(rangeChart(c, rk.policy || {}), el("p", "Shaded: where 80% of outcomes fell in calibration. Dot: the shrunk forecast used for decisions (hollow: raw forecast). Dashed lines: the buy threshold (cost + minimum edge), the avoid threshold, and the lowest 10% outcome the tail gate accepts.", "muted")); charts.append(c1);
    const c2 = card("What drives the forecast"); c2.append(contributionChart(c), el("p", "Each bar is one feature's contribution (coefficient × today's rank). Blue raises the forecast, red lowers it; signs are printed. The common part is the same for every stock today.", "muted")); charts.append(c2);
    const c3 = card("Where a round trip's cost goes"); c3.append(costBar(costs)); charts.append(c3);
  }
  const c4 = card("Price over the last year (" + c.symbol + " vs Nifty 50)"); c4.append(priceChart(d.prices || {}, c.symbol)); charts.append(c4);
  if (d.insights && d.insights.length) {
    const ic = card("What the numbers mean together", "wide"); body.append(ic);
    for (const i of d.insights) { const b = el("div", null, "insight " + i.code); b.append(el("strong", i.title), el("span", i.text)); for (const tm of i.terms || []) b.append(term(tm)); ic.append(b); }
  }
  const nc = card("The explanation, step by step", "wide"); body.append(nc);
  const ol = el("ol", null, "steps"); for (const s of d.narrative.slice(1)) { const li = el("li"); li.append(el("strong", s.title), el("span", s.text)); ol.append(li); } nc.append(ol);
  if (c.features) {
    const ft = card("Features: today's values and ranks", "wide"); body.append(ft);
    const items = (c.contributions || {}).items || [];
    const byF = {}; for (const it of items) byF[it.feature] = it;
    ft.append(table(["Feature", "Value", "Rank among stocks", "Coefficient β", "Contribution", "What it measures"], d.features_table.map(f => {
      const it = byF[f.feature] || {}; const mkt = it.group === "market";
      return [f.name, fmtFeature(f.feature, f.raw), f.x == null ? "–" : (mkt ? "z " + num(f.x, 2) : (100 * (f.x + 0.5)).toFixed(0) + "%"), it.beta == null ? "–" : num(it.beta, 4), it.contribution == null ? "–" : spct(it.contribution, 3), f.what];
    }), [1, 2, 3, 4]));
  }
  const ec = card("Eligibility checks (universe rules)"); body.append(ec);
  for (const ch of c.checks || []) { const r = el("div", null, "check"); r.append(el("span", ch.pass === true ? "✓" : ch.pass === false ? "✕" : "?", ch.pass === true ? "ok" : ch.pass === false ? "no" : "unk"), el("span", ch.rule.replaceAll("_", " ").toLowerCase() + ": " + fmtCheck(ch.value)), el("span", "needs " + fmtCheck(ch.need), "muted")); ec.append(r); }
  if (c.missing_features && c.missing_features.length) ec.append(el("p", "Missing features: " + c.missing_features.join(", "), "muted"));
  body.append(aiPanel(c, d));
}
function fmtCheck(v) { if (typeof v === "number") return v >= 1e7 ? crore(v) : v.toLocaleString("en-IN"); return v == null ? "unknown" : String(v); }
function fmtFeature(f, v) {
  if (v == null) return "–";
  if (["mom_12_1", "rev_5", "ret_20", "gap_1", "mkt_20", "mkt_60"].includes(f)) return spct(v);
  if (["vol_20", "park_20", "mkt_vol_20"].includes(f)) return pct(v) + "/day";
  if (f === "range_250" || f === "breadth_50") return (100 * v).toFixed(0) + "%";
  if (f === "lvalue_20") return crore(Math.exp(v));
  return num(v, 4);
}
function term(key) { const t = el("span", key.replaceAll("_", " "), "term"); t.tabIndex = 0; const g = (HOW && HOW.glossary && HOW.glossary[key]); tipOn(t, g ? [g.term, g.plain] : [key, "See How it works → Glossary."]); return t; }

// charts for one stock -------------------------------------------------------------------------------
function niceStep(span) { const raw = span / 5, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p; return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * p; }
function rangeChart(c, pol) {
  // Two rows on one % axis (both are 20-session log returns): the return against the Nifty 50 (what the edge gate
  // and the forecast are about) and the stock's own return (what the tail gate is about: money lost). E22.
  const fc = c.forecast, fl = c.flip || {}, cost = c.costs.cost_fraction, thr = cost + (pol.min_edge || 0);
  const absOk = fc.q10_abs != null && fc.q90_abs != null, tailQ = fl.tail_q10_threshold;
  const vals = [fc.q10, fc.q90, thr, -thr, fc.mu_hat, fc.mu_shrunk, 0].concat(absOk ? [fc.q10_abs, fc.q90_abs] : []).concat(tailQ != null ? [tailQ] : []).filter(v => v != null);
  const lo = Math.min(...vals), hi = Math.max(...vals), padv = (hi - lo) * 0.08 || 0.01, a = lo - padv, b = hi + padv;
  const W = 600, H = absOk ? 214 : 150, L = 16, R = 16, x = v => L + (v - a) / (b - a) * (W - L - R);
  const r1 = 52, r2 = 150, axisY = absOk ? 178 : 112;
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Forecast range chart: against the Nifty 50 and the stock's own return" });
  const step = niceStep(b - a);
  for (let t = Math.ceil(a / step) * step; t <= b; t += step) { s.append(svgEl("line", { x1: x(t), y1: 30, x2: x(t), y2: axisY, class: "grid" }), svgText(x(t), axisY + 16, (100 * t).toFixed(Math.abs(step) < 0.01 ? 1 : 0) + "%", { "text-anchor": "middle", class: "t-lab" })); }
  s.append(svgEl("line", { x1: L, y1: axisY, x2: W - R, y2: axisY, class: "axis" }));
  s.append(svgEl("line", { x1: x(0), y1: 30, x2: x(0), y2: axisY, class: "zero" }));
  s.append(svgText(L, r1 - 12, "Against the Nifty 50", { class: "t-lab" }));
  const band = svgEl("rect", { x: x(fc.q10), y: r1, width: Math.max(2, x(fc.q90) - x(fc.q10)), height: 22, rx: 4, class: "band" });
  tipOn(band, ["Return against the Nifty 50, 80% range", spct(fc.q10) + " to " + spct(fc.q90) + " (median " + spct(fc.q50) + ")"]); s.append(band);
  s.append(svgEl("line", { x1: x(fc.q50), y1: r1, x2: x(fc.q50), y2: r1 + 22, class: "q50" }));
  const lines = [[thr, "buy needs " + spct(thr)], [-thr, "avoid below " + spct(-thr)]].sort((p, q) => p[0] - q[0]);
  lines.forEach(([v, lab], i) => { s.append(svgEl("line", { x1: x(v), y1: r1 - 8, x2: x(v), y2: r1 + 30, class: "th-line" })); const an = x(v) > W * 0.7 ? "end" : x(v) < W * 0.3 ? "start" : "middle"; s.append(svgText(x(v), 12 + i * 11, lab, { "text-anchor": an, class: "t-val" })); });
  if (fc.mu_hat != null) { const r0 = svgEl("circle", { cx: x(fc.mu_hat), cy: r1 + 11, r: 4.5, class: "dot-raw" }); tipOn(r0, ["Raw forecast μ̂", spct(fc.mu_hat, 3) + (fc.mu_common != null ? " = market part " + spct(fc.mu_common, 3) + " + stock part " + spct(fc.mu_specific, 3) : " before shrinkage")]); s.append(r0); }
  const keep = fc.shrink_common != null ? "keeps " + (100 * fc.shrink_common).toFixed(0) + "% of the market part and " + (100 * fc.shrink_specific).toFixed(0) + "% of the stock part" : "keeps " + (100 * fc.shrink_factor).toFixed(0) + "% of the raw forecast";
  const d0 = svgEl("circle", { cx: x(fc.mu_shrunk), cy: r1 + 11, r: 6, class: "dot" }); tipOn(d0, ["Shrunk forecast μ̃", spct(fc.mu_shrunk, 3) + " (" + keep + ")"]); s.append(d0);
  s.append(svgText(x(fc.mu_shrunk), r1 + 40, "forecast " + spct(fc.mu_shrunk), { "text-anchor": x(fc.mu_shrunk) > W * 0.75 ? "end" : x(fc.mu_shrunk) < W * 0.25 ? "start" : "middle", class: "t-strong" }));
  if (absOk) {
    s.append(svgText(L, r2 - 12, "Your money: the stock's own return (no market drift assumed)", { class: "t-lab" }));
    const b2 = svgEl("rect", { x: x(fc.q10_abs), y: r2, width: Math.max(2, x(fc.q90_abs) - x(fc.q10_abs)), height: 22, rx: 4, class: "band" });
    tipOn(b2, ["Stock's own return, 80% range", spct(fc.q10_abs) + " to " + spct(fc.q90_abs) + " (median " + spct(fc.q50_abs) + ")", "q10 is the bad month the tail gate uses"]); s.append(b2);
    s.append(svgEl("line", { x1: x(fc.q50_abs), y1: r2, x2: x(fc.q50_abs), y2: r2 + 22, class: "q50" }));
    if (tailQ != null) {
      s.append(svgEl("line", { x1: x(tailQ), y1: r2 - 8, x2: x(tailQ), y2: r2 + 30, class: "th-line" }));
      const share = c.costs.value && pol.W ? c.costs.value / pol.W : null;
      const lab = "worst bad month accepted " + spct(tailQ) + (share != null ? " (" + (100 * share).toFixed(0) + "% of capital at risk, limit " + spct(-(pol.tail_limit || 0.08)) + " of capital)" : "");
      s.append(svgText(x(tailQ), r2 + 42, lab, { "text-anchor": x(tailQ) > W * 0.6 ? "end" : x(tailQ) < W * 0.4 ? "start" : "middle", class: "t-val" }));
    }
  }
  return s;
}
function contributionChart(c) {
  const con = c.contributions, items = [...con.items].sort((p, q) => Math.abs(q.contribution) - Math.abs(p.contribution));
  const rows = items.filter(i => i.group === "stock").concat([{ feature: "_common", contribution: con.common_total, label: "Common part (intercept + market)" }]);
  const W = 600, rowH = 24, H = rows.length * rowH + 30, mid = 330, max = Math.max(1e-6, ...rows.map(r => Math.abs(r.contribution || 0))), sc = 200 / max;
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Contributions to the forecast" });
  rows.forEach((r, i) => {
    const v = r.contribution || 0, y = i * rowH + 6, w = Math.max(1, Math.abs(v) * sc);
    const info = (HOW && HOW.features && HOW.features[r.feature]) || null, name = r.label || (info ? info.name : r.feature);
    const bar = svgEl("rect", { x: v >= 0 ? mid : mid - w, y, width: w, height: 13, rx: 3, class: v >= 0 ? "m-pos" : "m-neg" });
    tipOn(bar, [name, "contribution " + spct(v, 3) + (r.beta != null ? " = β " + num(r.beta, 4) + " × rank " + num(r.x, 3) : ""), info ? info.what : "The same for every stock today."]);
    s.append(bar, svgText(mid - 8 - (v < 0 ? w : 0), y + 11, String(name).slice(0, 40), { "text-anchor": "end", class: "t-lab" }), svgText(v >= 0 ? mid + w + 6 : mid + 6, y + 11, spct(v, 2), { class: "t-val" }));
  });
  s.append(svgEl("line", { x1: mid, y1: 0, x2: mid, y2: H - 22, class: "axis" }));
  s.append(svgText(W - 4, H - 6, "raw forecast μ̂ = " + spct(c.forecast.mu_hat, 3), { "text-anchor": "end", class: "t-strong" }));
  return s;
}
function costBar(costs) {
  const w = el("div"), sell = Math.max(0, (costs.sell_charges_incl_dp || 0) - (costs.dp_charge || 0));
  const parts = [["Buy charges (STT, stamp, exchange, SEBI, GST)", costs.buy_charges || 0, "f1", false], ["Sell charges (STT, exchange, SEBI, GST)", sell, "f2", false], ["DP charge (fixed per sell)", costs.dp_charge || 0, "f3", false], ["Slippage, both ways (modelled)", costs.slippage_rupees || 0, "f4", true]];
  const total = parts.reduce((a, p) => a + p[1], 0) || 1, W = 600, H = 34;
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Cost breakdown" });
  let x0 = 0;
  parts.forEach(([lab, v, cls, dark], i) => {
    const wd = v / total * W; if (wd <= 0) return;
    const r = svgEl("rect", { x: x0, y: 2, width: Math.max(0, wd - (i < parts.length - 1 ? 2 : 0)), height: 28, rx: 4, class: cls }); tipOn(r, [lab, money(v) + " (" + (100 * v / total).toFixed(0) + "% of the cost)"]); s.append(r);
    if (wd > 46) s.append(svgText(x0 + 8, 20, (100 * v / total).toFixed(0) + "%", { class: "t-in" + (dark ? " dark" : "") }));
    x0 += wd;
  });
  w.append(s);
  const lg = el("div", null, "legend"); parts.forEach(([lab, v], i) => { const it = el("span", null, "lg"); it.append(el("i", null, "sw s" + (i + 1)), el("span", lab + ": " + money(v))); lg.append(it); });
  w.append(lg, el("p", "Total " + money(total) + " on a " + money(costs.value) + " position (" + costs.q + " shares) = " + pct(costs.cost_fraction) + " for a buy and a later sell. Charges follow Zerodha's published schedule; slippage is a model.", "muted"));
  return w;
}
function priceChart(p, sym) {
  const days = p.days || [], cl = p.close || [], ix = p.index || [];
  if (!days.length) return el("p", "No price history in the panel.", "muted");
  const W = 600, H = 190, L = 8, R = 60, T = 10, B = 26, all = cl.concat(ix.filter(v => v != null));
  const lo = Math.min(...all), hi = Math.max(...all), x = i => L + i / Math.max(1, days.length - 1) * (W - L - R), y = v => T + (hi === lo ? 0.5 : (hi - v) / (hi - lo)) * (H - T - B);
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Price chart" });
  for (let k = 0; k <= 3; k++) { const v = lo + (hi - lo) * k / 3; s.append(svgEl("line", { x1: L, y1: y(v), x2: W - R, y2: y(v), class: "grid" }), svgText(W - R + 4, y(v) + 4, v.toFixed(v >= 1000 ? 0 : 1), { class: "t-lab" })); }
  const path = vs => vs.map((v, i) => v == null ? "" : ((i === 0 || vs[i - 1] == null) ? "M" : "L") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  s.append(svgEl("path", { d: path(ix), fill: "none", class: "ln s2" }), svgEl("path", { d: path(cl), fill: "none", class: "ln s1" }));
  s.append(svgText(L, H - 8, days[0], { class: "t-lab" }), svgText(W - R, H - 8, days[days.length - 1], { "text-anchor": "end", class: "t-lab" }));
  (p.listed_actions || []).forEach(dd => { const i = days.indexOf(dd); if (i >= 0) { const m = svgEl("rect", { x: x(i) - 3, y: H - B - 6, width: 6, height: 6, class: "mark-act" }); tipOn(m, ["Listed corporate action " + dd, "Earlier prices restated in today's units"]); s.append(m); } });
  (p.unexplained_jumps || []).forEach(dd => { const i = days.indexOf(dd); if (i >= 0) { const m = svgEl("rect", { x: x(i) - 1, y: T, width: 2, height: H - T - B, class: "mark-bad" }); tipOn(m, ["Unexplained price jump " + dd, "No listed action explains it: returns across it are not used"]); s.append(m); } });
  const cross = svgEl("line", { x1: 0, y1: T, x2: 0, y2: H - B, class: "cross", visibility: "hidden" }); s.append(cross);
  const hit = svgEl("rect", { x: L, y: T, width: W - L - R, height: H - T - B, class: "hit" });
  hit.addEventListener("mousemove", e => {
    const box = s.getBoundingClientRect ? s.getBoundingClientRect() : null; if (!box || !box.width) return;
    const vx = (e.clientX - box.left) / box.width * W, i = Math.max(0, Math.min(days.length - 1, Math.round((vx - L) / (W - L - R) * (days.length - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    showTip(e, [days[i], sym + " " + money(cl[i]), "Nifty 50 (rebased) " + (ix[i] == null ? "n/a" : money(ix[i]))]);
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  s.append(hit);
  const w = el("div"); w.append(s);
  const lg = el("div", null, "legend"); for (const [k, lab] of [[1, sym + " close" + (p.log_note ? " (" + p.log_note + ")" : "")], [2, "Nifty 50, rebased to the same start"]]) { const it = el("span", null, "lg"); it.append(el("i", null, "sw s" + k), el("span", lab)); lg.append(it); }
  w.append(lg); return w;
}

// ---- AI panel ----------------------------------------------------------------------------------------
const PRESET_LABELS = { explain: "Explain everything", maths: "The maths, step by step", together: "What it means together", risks: "What could go wrong", change: "What would change the call" };
function aiPanel(c, d) {
  const p = card("Ask AI about " + c.symbol, "wide");
  p.append(el("p", "Optional. Uses your own Google Gemini or Anthropic API key and spending caps (Controls & AI). The model sees only this stock's card, the explanation above and the glossary: no account data. Its answer is labelled commentary and never changes the ranking.", "muted"));
  const status = el("p", "Checking AI settings…", "muted"); p.append(status);
  const presets = el("div", null, "presets"); const qa = el("textarea"); qa.placeholder = "Or ask your own question about " + c.symbol + " (optional)…"; qa.maxLength = 1500;
  const est = el("p", "", "muted"), out = el("div"), btn = el("button", "Ask", "button primary"); btn.type = "button";
  let preset = "explain";
  for (const [k, lab] of Object.entries(PRESET_LABELS)) { const b = el("button", lab, "button small"); b.type = "button"; b.addEventListener("click", () => { preset = k; qa.value = ""; for (const x of $$("button", presets)) x.classList.toggle("primary", x === b); }); if (k === preset) b.classList.add("primary"); presets.append(b); }
  p.append(presets, qa, el("div", null, "actions").appendChild(btn).parentNode, est, out);
  get("/api/ai/status").then(ai => {
    const k = ai.key || {};
    if (!k.set) { status.textContent = "No API key set. Add one in Controls & AI to enable explanations."; btn.disabled = true; const go = el("button", "Open AI settings", "button small"); go.type = "button"; go.addEventListener("click", () => { closeSheet(); show("controls"); }); status.append(" ", go); return; }
    if (!ai.sdk_installed && ai.provider === "anthropic") { status.textContent = "The Anthropic SDK is not installed on the server (pip install anthropic)."; btn.disabled = true; return; }
    status.textContent = (ai.provider === "gemini" ? "Google Gemini · " + (ai.active_model || ai.settings.gemini_model) + (ai.settings.fallback ? " (falls back to Flash-Lite when busy)" : "") : "Model " + ai.settings.model) + " · up to " + ai.settings.max_tokens + " output tokens · spent today $" + ai.spent.day_usd + " of $" + ai.caps.daily_usd + ".";
    get("/api/ai/estimate?isin=" + encodeURIComponent(c.isin)).then(e => { if (!e.error) est.textContent = e.provider === "gemini" ? "This ask reserves up to $" + e.reserve_usd + " against your caps (list-price equivalent, about $" + e.typical_usd_first + " typical). On the free tier Google bills $0." : "This ask reserves up to $" + e.reserve_usd + " against your caps; typical cost about $" + e.typical_usd_first + " (first ask) or $" + e.typical_usd_cached + " once the shared instructions are cached."; }).catch(() => {});
  }).catch(e => { status.textContent = "AI status unavailable: " + e.message; });
  btn.addEventListener("click", async () => {
    btn.disabled = true; out.replaceChildren(el("p", "Asking… a detailed answer can take a minute or two.", "muted"));
    try {
      const j = await post("/api/ai/ask", { isin: c.isin, preset, question: qa.value });
      for (let i = 0; i < 240; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const s = await get("/api/ai/job?id=" + encodeURIComponent(j.id));
        if (s.state === "RUNNING") continue;
        out.replaceChildren(s.record ? answerView(s.record) : el("p", "Failed: " + (s.error || "unknown") + (s.detail ? " (" + s.detail + ")" : ""), "warn-text"));
        break;
      }
    } catch (e) { out.replaceChildren(el("p", "Refused: " + e.message, "warn-text")); }
    btn.disabled = false;
  });
  const hist = d.ai_history || [];
  if (hist.length) { p.append(el("h3", "Earlier answers for " + c.symbol)); for (const a of hist) { const dt = el("details"); dt.append(el("summary", String(a.created_at || "").replace("T", " ").slice(0, 16) + " · " + (a.state || "") + " · " + String(a.question || "").slice(0, 80))); dt.append(answerView(a)); p.append(dt); } }
  return p;
}
function answerView(a) {
  const w = el("div", null, "ai-answer");
  w.append(el("div", "AI commentary · not a MarketLab calculation · never a decision input", "ai-label"));
  if (a.state === "FAILED") { w.append(el("p", "Failed: " + a.error, "warn-text")); return w; }
  if (a.state === "REFUSED") w.append(el("p", "The model declined this request" + (a.stop_category ? " (" + a.stop_category + ")" : "") + ".", "warn-text"));
  if (a.state === "TRUNCATED") w.append(el("p", "The answer hit the output limit and is cut short (raise max output tokens in AI settings).", "warn-text"));
  w.append(renderMarkdown(a.answer || ""));
  if (a.unsourced_numbers && a.unsourced_numbers.length) w.append(el("p", "Numbers in this answer that are not on MarketLab's card (the AI's own, unverified): " + a.unsourced_numbers.join(", "), "warn-text"));
  w.append(el("p", "Model " + (a.model_served || a.model_requested || "?") + (a.fallback_switches && a.fallback_switches.length ? " (fallback used)" : "") + " · cost $" + (a.cost_usd || "?") + " · " + String(a.created_at || "").replace("T", " ").slice(0, 16), "muted"));
  return w;
}
function inline(text) {
  const f = el("span"), parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/);
  for (const part of parts) { if (!part) continue; if (part.startsWith("**") && part.endsWith("**")) f.append(el("strong", part.slice(2, -2))); else if (part.startsWith("`") && part.endsWith("`")) f.append(el("code", part.slice(1, -1))); else f.append(document.createTextNode ? document.createTextNode(part) : el("span", part)); }
  return f;
}
function renderMarkdown(text) {
  const root = el("div"); let list = null, para = [];
  const flush = () => { if (para.length) { const p = el("p"); p.append(inline(para.join(" "))); root.append(p); para = []; } };
  for (const raw of String(text).split("\n")) {
    const line = raw.trimEnd(), t = line.trim();
    if (!t) { flush(); list = null; continue; }
    const hm = t.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { flush(); list = null; const h = el(hm[1].length <= 2 ? "h4" : "h5"); h.append(inline(hm[2])); root.append(h); continue; }
    const um = t.match(/^[-*•]\s+(.*)$/), om = t.match(/^\d+[.)]\s+(.*)$/);
    if (um || om) { flush(); const kind = um ? "ul" : "ol"; if (!list || list.tagName !== kind) { list = el(kind); root.append(list); } const li = el("li"); li.append(inline((um || om)[1])); list.append(li); continue; }
    list = null; para.push(t);
  }
  flush(); return root;
}

// ---- How it works ----------------------------------------------------------------------------------
let HOW = null;
async function renderHow() {
  const t = tab("how"); t.append(el("p", "Loading…", "muted"));
  HOW = await get("/api/how"); t.replaceChildren();
  const hero = el("section", null, "hero"); hero.append(el("h2", "How MarketLab decides, and what it all means")); t.append(hero);
  const mc = card("What this all means"); const ul = el("ul"); for (const m of HOW.meaning || []) ul.append(el("li", m)); mc.append(ul); t.append(mc);
  if (HOW.today && HOW.today.length) { const tc = card("What the latest ranking says"); const tl = el("ul"); for (const m of HOW.today) tl.append(el("li", m)); tc.append(tl); t.append(tc); }
  if (HOW.reviews && HOW.reviews.length) {
    const rc = card("Checks on this model, and what became of each finding");
    rc.append(el("p", "Every outside review is listed with its outcome. A finding is closed only by a fix with a test, or by evidence that it was wrong.", "muted"));
    rc.append(table(["When", "Who", "Finding", "Outcome", "Where"], HOW.reviews.map(x => [x.date, x.by, x.finding, x.status, x.where])));
    t.append(rc);
  }
  const pc = card("The pipeline, step by step (live status from the latest ranking)"); t.append(pc);
  (HOW.stages || []).forEach((s, i) => {
    const st = el("div", null, "stage"); st.append(el("div", String(i + 1), "no"));
    const b = el("div"); b.append(el("strong", s.title.replace(/^\d+\.\s*/, "")), el("p", s.what));
    if (s.maths) b.append(el("pre", s.maths, "maths"));
    if (s.status) b.append(el("span", "Now: " + s.status, "pill"));
    st.append(b); pc.append(st);
  });
  const cc = card("The calls and their exact rules"); t.append(cc);
  for (const [k, v] of Object.entries(HOW.classes || {})) { const r = el("div", null, "item"); const h = el("div"); h.append(badge(k)); r.append(h, el("p", v.means), el("p", "Rule: " + v.rule, "muted")); cc.append(r); }
  const fcard = card("The features the model reads"); t.append(fcard);
  fcard.append(table(["Feature", "What it measures", "Formula", "High means", "Low means"], Object.entries(HOW.features || {}).map(([k, f]) => [f.name, f.what, f.formula, f.high, f.low])));
  const gc = card("Glossary"); t.append(gc);
  const q = el("input"); q.type = "search"; q.placeholder = "Filter terms…"; gc.append(q); const gl = el("div"); gc.append(gl);
  const draw = () => { gl.replaceChildren(); const ql = q.value.toLowerCase(); for (const [k, g] of Object.entries(HOW.glossary || {}).sort((a, b) => a[1].term.localeCompare(b[1].term))) { if (ql && !(g.term + " " + g.plain).toLowerCase().includes(ql)) continue; const e = el("div", null, "gl"); e.append(el("strong", g.term), el("span", g.plain)); if (g.formula) e.append(el("pre", g.formula, "maths")); gl.append(e); } };
  q.addEventListener("input", draw); draw();
  const rc = card("Ranking files (write-once; forward evidence only if recorded before the next session opened)"); t.append(rc);
  const rs = HOW.rankings || [];
  rc.append(rs.length ? table(["Day", "Created", "Digest", "Status", "Forward evidence", "Buy / qualify / avoid"], rs.slice().reverse().map(r => [r.day, String(r.created_at || "").replace("T", " ").slice(0, 16), String(r.digest || "").slice(0, 12), r.status, (r.forward || {}).eligible ? "yes" : "no", r.counts ? [r.counts.BUY_CANDIDATE, r.counts.QUALIFIES, r.counts.AVOID].join(" / ") : ""])) : el("p", "No ranking recorded yet.", "muted"));
}
"""
