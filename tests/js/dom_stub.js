// Minimal DOM to execute the dashboard renderers against real API JSON (runtime errors and leaked raw values).
// Usage: node dom_stub.js <app.js> <fixtures.json>   -> prints RENDER_OK lines or exits 1.
"use strict";
const fs = require("fs");
const [appPath, dataPath] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
class ClassList {
  constructor(n) { this.n = n; }
  _set() { return new Set(String(this.n.className || "").split(/\s+/).filter(Boolean)); }
  add(...c) { const s = this._set(); c.forEach(x => s.add(x)); this.n.className = [...s].join(" "); }
  remove(...c) { const s = this._set(); c.forEach(x => s.delete(x)); this.n.className = [...s].join(" "); }
  contains(c) { return this._set().has(c); }
  toggle(c, force) { const has = this._set().has(c); const want = force === undefined ? !has : !!force; if (want) this.add(c); else this.remove(c); return want; }
}
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this._text = ""; this.className = ""; this.hidden = false; this.dataset = {}; this.value = ""; this.listeners = {}; this.style = {}; this.parentNode = null; this.classList = new ClassList(this); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(""); }
  append(...xs) { for (const x of xs) { const n = typeof x === "string" ? Object.assign(new Node("#text"), { _text: x }) : x; n.parentNode = this; this.children.push(n); } }
  appendChild(x) { this.append(x); return x; }
  prepend(...xs) { for (const x of xs.reverse()) { x.parentNode = this; this.children.unshift(x); } }
  replaceChildren(...xs) { this.children = []; this._text = ""; this.append(...xs); }
  setAttribute(k, v) { if (typeof v === "number" && !Number.isFinite(v)) throw new Error("non-finite SVG attribute " + k); if (String(v).includes("NaN")) throw new Error("NaN in SVG attribute " + k + "=" + v); this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); }
  async fire(k, e = {}) { for (const f of this.listeners[k] || []) await f(Object.assign({ target: this, clientX: 10, clientY: 10, key: "Enter" }, e)); }
  focus() {} remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(c => c !== this); }
  _all() { const out = []; const walk = n => { for (const c of n.children) { out.push(c); walk(c); } }; walk(this); return out; }
  _match(sel) { if (sel.startsWith("#")) return n => n.attrs.id === sel.slice(1); if (sel.startsWith(".")) return n => n.classList.contains(sel.slice(1)); return n => n.tagName === sel; }
  querySelector(sel) { return this._all().find(this._match(sel)) || null; }
  querySelectorAll(sel) { return this._all().filter(this._match(sel)); }
  getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 200 }; }
}
const ids = {};
for (const id of ["chips", "offline", "theme", "sheet", "sheet-body", "tip", "tabs"].concat(["stocks", "how", "overview", "data", "universe", "forecasts", "evaluation", "controls"].map(t => "tab-" + t))) { ids[id] = new Node("div"); ids[id].attrs.id = id; }
global.document = {
  documentElement: { dataset: {} }, body: new Node("body"),
  createElement: t => new Node(t), createElementNS: (_, t) => new Node(t), createTextNode: t => Object.assign(new Node("#text"), { _text: String(t) }),
  querySelector: s => s.startsWith("#") ? ids[s.slice(1)] || null : null, querySelectorAll: () => [], addEventListener: () => {},
};
global.window = { innerWidth: 1200 };
Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true, writable: true });
Object.defineProperty(globalThis, "localStorage", { value: { getItem: () => null, setItem: () => {} }, configurable: true, writable: true });
global.alert = m => { throw new Error("alert: " + m); };
const calls = [];
global.fetch = async (path, opts) => {
  calls.push(path);
  const full = decodeURIComponent(path), key = full in data ? full : path.split("?")[0];
  if (!(key in data)) throw new Error("no stub for " + path);
  return { ok: true, status: 200, json: async () => data[key] };
};
const src = fs.readFileSync(appPath, "utf8");
eval(src + "\n;global.__r = { renderStocks, renderHow, renderOverview, renderControls, renderForecasts, renderEvaluation, renderData, openStock, renderMarkdown, applyTheme };");
function check(name, node) {
  const text = node.textContent;
  for (const bad of ["undefined", "NaN", "[object Object]", "Infinity"]) {
    if (text.includes(bad)) { console.log("BAD " + name + " contains " + bad + ": …" + text.slice(Math.max(0, text.indexOf(bad) - 160), text.indexOf(bad) + 60)); process.exitCode = 1; }
  }
  console.log("RENDER_OK " + name + " chars=" + text.length);
  return text;
}
(async () => {
  await __r.renderStocks(true);
  check("stocks", ids["tab-stocks"]);
  const row = ids["tab-stocks"]._all().find(n => n.tagName === "tr" && n.classList.contains("click") && n.textContent.includes(data.__isin_symbol));
  if (!row) throw new Error("no clickable row for " + data.__isin_symbol);
  await row.fire("click");
  await new Promise(r => setTimeout(r, 20));
  const sheet = check("stock_sheet", ids["sheet-body"]);
  for (const want of ["The explanation, step by step", "What drives the forecast", "Ask AI about", "Eligibility checks"]) if (!sheet.includes(want)) { console.log("MISSING in sheet: " + want); process.exitCode = 1; }
  await __r.renderHow(); check("how", ids["tab-how"]);
  __r.renderOverview(data["/api/status"]); check("overview", ids["tab-overview"]);
  await __r.renderControls(); check("controls", ids["tab-controls"]);
  await __r.renderForecasts(); check("decision", ids["tab-forecasts"]);
  await __r.renderEvaluation(); check("evaluation", ids["tab-evaluation"]);
  await __r.renderData(); check("data", ids["tab-data"]);
  const md = __r.renderMarkdown("## Summary\nText with **bold** and `code`.\n- one\n- two\n1. first\n\nPara.");
  if (md.children.length !== 5) { console.log("BAD markdown blocks " + md.children.length); process.exitCode = 1; }
  console.log("FETCHED " + calls.length);
})().catch(e => { console.error("RENDER_FAIL", e && e.stack || e); process.exit(1); });
