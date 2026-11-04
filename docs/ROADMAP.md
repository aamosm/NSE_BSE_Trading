# Roadmap: from read-only data to an analysis machine

Status date: 4 November 2026. This file has three parts:
1. What is left of the original plan.
2. The next steps in order.
3. Who does what: Claude, GPT, and the two Fable sessions.

## 1. The original plan (starter kit phases 0–10) and what is left

| Original item | Status now |
| --- | --- |
| Phase 0: environment, rules register, architecture, data inventory | **Done**, then reset to cash-only. The active register is `docs/RULES_REGISTER.md`; the old documents are in `archive/phase_0_1/docs/` |
| Phase 1: cash **and MTF** double-entry ledger with hand-worked fixtures | MTF **removed by user decision**. The cash ledger is archived, not active. **Left:** a reconciled cash paper account (milestone F), fixing review findings R03, R06 and R07 when it is rebuilt |
| Phase 2: point-in-time data and evidence | **Partly done:** append-only evidence store with publication/receipt times, RSS import, bounded history download, dataset audit. **Left:** ISIN security master with listing history (A); official calendar and restriction ingestion (B, data side); corporate actions and raw/adjusted prices (C); bounded official-feed job (D); typed financial/event extraction (E) |
| Phase 3: replay clock, simulated broker (partial fills, lost acknowledgements, duplicates, restart, durable intents) | **Not built.** Only a one-instrument diagnostic simulator exists. With orders out of scope, this reduces to a realistic *paper* fill model and a durable paper-order log |
| Phase 4: forecasts, allocator, risk | **Contract only:** `Forecast`, one-entry paper sizing, now gated by the rules engine. **Left:** real models, a multi-asset integer allocator and a serialized paper coordinator (G) |
| Phase 5: 1,200 scenarios and 1,000 research trials | Replaced by: at least 1,000 *engineering* scenarios plus a *small preregistered* strategy set (the old registries are archived). Metrics exist: PSR, DSR, PBO with midranks, MinTRL. **Left:** the harness, purged walk-forward runner, ablations and model cards |
| Phase 6: React/TypeScript phone dashboard | Only a loopback status page. **Left:** the real dashboard, later |
| Phase 7: broker read-only integration and reconciliation | **Read-only collection verified on the real account.** **Left:** reconcile broker positions/cash against our books, manual-trade detection, contract-note/statement imports, order-update stream |
| Phase 8: hosted paper service | Laptop for now; systemd units exist in `deploy/`. **Left:** scheduled collection on the laptop (Task Scheduler), backups, then a server later |
| Phase 9: Android package | Not started (later) |
| Phase 10: limited live release | **Out of scope.** No live switch exists |
| Rules open items | 15 items in `RULES_REGISTER.md` §10. Most relevant: BSE and 2027 calendars, Muhurat timings, contract-note rounding, DDPI/eDIS for CNC sells |

## 2. Next logical steps (in order)

The bottleneck is **data, not models**. A model trained on data that silently leaks the future, or that lacks dead stocks, will look good and fail. The order below builds a measuring instrument first.

1. **Security master (A).** Daily snapshot of the Kite instrument dump plus NSE's official equity list (ISIN, series, face value, listing date), keyed by ISIN with effective dates. Today's account data already shows why: the same company appears as RCOM and RCOM-BE.
2. **Daily rule inputs (B, data side).** A builder that produces each day's `InstrumentSnapshot` from:
   - the master;
   - NSE price-band files;
   - GSM, ASM and ESM surveillance lists;
   - F&O membership.

   It also needs the 2027 NSE calendar and the 2026/2027 BSE calendars from official circulars. After this, the rules engine runs on real daily data instead of hand-made fixtures.
3. **Price store with corporate actions (C).** Raw daily OHLCV from Kite for a bounded universe (30–50 liquid stocks to start, 5+ years), split/bonus/dividend events with ex-dates, and raw and adjusted series kept apart. It must be verified whether Kite candles are already adjusted.
4. **Laptop collector schedule.** Windows Task Scheduler: one login reminder per day, after-close candles, master snapshot and evidence backup.
5. **Data readiness report.** What exists, per field, per year, with gaps and licensing. **This is the input to Fable session 1.**
6. **Fable session 1, design freeze** (below). Fable writes the maths and the evaluation protocol; Claude does not invent models.
7. **Claude implements Fable's specification:**
   - labels and features;
   - purged walk-forward runner;
   - baselines (cash, Nifty ETF buy-and-hold, equal weight);
   - integer, cost-aware allocator with the DP-charge non-convexity;
   - cash paper ledger (F) and serialized coordinator (G);
   - at least 1,000 engineering scenarios.
8. **GPT validates** with `prompts/03_VALIDATION.txt` and reviews with `prompts/04_INDEPENDENT_REVIEW.txt`.
9. **Prospective paper observation** for several weeks (no real orders), recorded daily.
10. **Fable session 2, evidence audit** (below): decide promote, reject or redesign.

## 3. Using Fable twice (limited tokens, heavy reasoning only)

Fable is used only where wrong reasoning is expensive and hard to detect: research design and the final statistical judgement. Bulk code, plumbing and routine reviews go to Claude and GPT. Each session gets a **small, curated input bundle**, never the whole repository.

**Session 1, design freeze** (after step 5). Prompt: `prompts/02_FABLE_SESSION_1_DESIGN.txt`.

Input bundle:
- FABLE_HANDOFF.md;
- the data readiness report;
- `docs/FABLE_MATH_SPEC.md`;
- `docs/RESEARCH_BRIEF.md`;
- the cost model summary (`docs/METRICS`-style break-even table);
- `src/marketlab/research.py`.

Expected output:
1. Exact label and information-set definitions per horizon.
2. At most 6 preregistered candidates and their ablations.
3. The evaluation protocol: purging, embargo, holdout and promotion rule.
4. A small-capital integer allocation formulation.
5. A power / minimum-track-record analysis: can an edge of plausible size even be detected net of ₹15.34 DP charges at ₹10,000?
6. Function signatures with hand-worked test vectors for Claude.

**Session 2, evidence audit** (after steps 7–9). Prompt: `prompts/05_FABLE_SESSION_2_AUDIT.txt`.

Input bundle:
- the frozen registry;
- every trial's results, including failures;
- calibration and cost tables;
- PBO/DSR outputs;
- the paper-observation log;
- GPT's validation report.

Expected output:
- a leakage and selection-bias judgement;
- per-candidate promote or reject against the preregistered rule;
- what the evidence can and cannot support;
- the next research cycle, if any.

**Everything else goes to GPT:** milestone reviews, searches for sources and facts, validation runs, planning between sessions.

## 4. Search requests (for GPT or the searching assistant)

1. Are Kite Connect historical daily candles adjusted for splits, bonuses and dividends? Which, and since when?
2. Official URLs and formats for NSE's daily price-band file, the GSM/ASM/ESM lists and the equity master (EQUITY_L), plus archive depth.
3. NSE 2027 trading and settlement holiday circulars (when published); BSE 2026 and 2027 holiday notices.
4. Muhurat trading timings for 8 Nov 2026 (NSE circular).
5. Zerodha contract-note rounding of STT and stamp duty, and whether DP is charged per scrip per day. One real contract note from the user would settle this.
