# Fable handoff (input to session 1: design freeze)

Prepared 5 November 2026. **Do not spend the session yet.** Session 1 should start only after the backfills in `DATA_READINESS.md` §4 (steps 1–3) are done and this file is refreshed with the real coverage numbers.

Allowed outcome: **INSUFFICIENT DATA**, per horizon, with the data that would change it.

Attach exactly these files:
- this file;
- `DATA_READINESS.md`;
- `docs/FABLE_MATH_SPEC.md`;
- `docs/RESEARCH_BRIEF.md`;
- `prompts/02_FABLE_SESSION_1_DESIGN.txt` (the prompt).

## 1. Fixed constraints

- **Scope:** long-only NSE/BSE cash equities, integer shares, about ₹10,000 of simulated capital, one shared cash book. No MTF, borrowing, shorting, derivatives or real orders.
- **Paper only:** the design will run in REPLAY and FORWARD_PAPER adapters around one decision engine. Neither has order capability.
- **Proposal gate:** every proposal passes the exchange-rules engine on a dated `InstrumentSnapshot`. Unknown required inputs block.
- **Information timing:** at decision time t, only data whose first receipt (or, for reconstructed history, documented publication) is ≤ t. End-of-day files are available after the close. NSE's after-close sec_list and REG1_IND describe the next session.
- **NSE closing price:** a closing-auction price for CAS stocks from 3 Aug 2026, and a VWAP-based close otherwise. Entry and exit must be at a tradable price after the decision.

## 2. Schemas that exist (code is the authority)

| Object | Module | Fields |
| --- | --- | --- |
| `Forecast` | `research.py` | isin, exchange, sector, sleeve (core/swing/intraday), as_of, expires_at, horizon_sessions, mean_return, q10, q50, q90, mean_standard_error, probability_positive, samples, model_id, calibration_id, evidence_ids, validated_for_paper |
| `InstrumentSnapshot` | `rules/types.py` | as_of, exchange, symbol, isin, series, has_derivatives, base_price, price_band_pct, tick_size, tick_reference_price, ltp, dynamic_band_pct, cas_reference_price, surveillance{framework, stage}, in_periodic_call_auction, suspended, special_preopen_today, mis_eligible, snapshot_id (None = unknown = blocks) |
| Snapshot provenance | `master.build_nse_snapshot` | per field: PRIMARY / CROSS_CHECKED / ASSUMPTION / UNKNOWN, input file key, SHA-256, receipt time |
| Price series | `corporate_actions.py` | kind: PROVIDER_ORIGINAL, EXCHANGE_UNADJUSTED, DERIVED_ADJUSTED, DERIVED_TOTAL_RETURN; plus isin, source, retrieved_at (vintage), basis, bars(day, OHLC, volume), applied_action_ids, parent_series_id |
| Corporate action | `corporate_actions.py` | action_id, isin, kind (SPLIT/BONUS/DIVIDEND/RIGHTS/SPIN_OFF), ex_date, record_date, payment_date, old_fv/new_fv, ratio_new/ratio_held, cash_per_share, source, published_at, first_seen_at |
| Day charges | `rules/charges.day_charges` | STT groups (exchange, ISIN, date, kind, side → whole-rupee STT), per-order components, DP, totals, assumptions |
| Paper decision | `service.record_decision` | day, action, reasons[], symbols, explanation (from reason codes), model_id, simulated=true |
| Proposal | `research.paper_proposal` | ABSTAIN reasons or PAPER_BUY_PROPOSAL{quantity, net_score, round_trip_cost_estimate, rule_warnings, snapshot_id, evidence_ids, model_id} |

**Gaps in the forecast contract for you to specify:** target/return definition, cost inclusion, data-coverage fields, the tail-loss measure, and how REDUCE/EXIT/HOLD are proposed. Only a BUY entry exists today.

## 3. Cost specification (Zerodha snapshot 4 Nov 2026; NSE)

Formulas:
- **Per executed order:**
  - brokerage: delivery 0; intraday min(0.03%, ₹20);
  - exchange transaction 0.00307% (NSE; BSE by group from listing data: 0.00375% default, 0.1% X/XT/Z/ZP, 1% SS/ST, 0.00275% M/MT/TS/MS);
  - SEBI ₹10 per crore;
  - NSE IPFT ₹0.01 per crore;
  - GST 18% of (brokerage + exchange + SEBI + IPFT);
  - stamp duty on buys: delivery 0.015%, intraday 0.003%. **Allocation unresolved.**
- **STT, per exchange/ISIN/date/kind/side:**
  - rate: delivery 0.1% both sides; intraday 0.025% on sells;
  - applied to (aggregate value ÷ quantity, rounded to the paisa) × quantity;
  - rounded to the nearest rupee, 50 paise up;
  - **the aggregation basis is an assumption.**
- **DP:** ₹15.34 per ISIN per delivery sell day, irrespective of quantity (₹15.05 for a female primary holder). Debited in the funds statement.

Round trip, same price, one order per side (computed by the code):

| Position | Kind | Buy | Sell (incl. DP) | Total | Break-even move |
| --- | --- | --- | --- | --- | --- |
| ₹1,000 | delivery | 1.19 | 16.38 | 17.57 | 1.76% |
| ₹2,000 | delivery | 2.37 | 17.41 | 19.78 | 0.99% |
| ₹5,000 | delivery | 5.94 | 20.53 | 26.47 | 0.53% |
| ₹10,000 | delivery | 11.88 | 25.72 | 37.60 | 0.38% |
| ₹10,000 | intraday | 4.22 | 6.92 | 11.14 | 0.11% (before spread) |

The table excludes the fixed ₹500/month Kite plan, the server (about US$12/month) and spread/slippage. Spread and slippage need prospective quote data.

## 4. Data available after the planned backfill (expected; confirm before the session)

- **Daily actual prices:** NSE from 2016 (two file formats) and BSE from Jul 2024, survivorship-aware by construction (daily traded universe).
- **Tradability:** static bands and series from 2022; surveillance stages from 2025; F&O membership current-only. Earlier rule inputs are unknown, so replays before 2022 cannot apply band and surveillance rules.
- **Benchmarks:** NSE index closes from 2020, price only.
- **Events:** RSS from 5 Nov 2026 only, plus whatever announcement history is retrievable. Corporate-action history is **not yet located**.
- **Not available:** intraday unadjusted prices, historical depth, broker MIS lists, fundamentals.

## 5. Questions that need your reasoning

1. **Feasibility and power.** For core and swing, given the cost table, integer shares at ₹10,000 and the number of effectively independent observations available: what is the minimum detectable net edge, and the minimum track record (with assumptions)? Which horizons should be declared INSUFFICIENT DATA now?
2. **Labels.** Exact entry rule (next tradable price after decision: next open? pre-open equilibrium?). Exit rule and label end time for purging. Treatment when daily bars cannot order stop and target (a conservative convention, or exclusion).
3. **Corporate actions in labels.** Build total-return labels only from EXCHANGE_UNADJUSTED + official actions. Until the history exists, should windows with a previous-close discontinuity be excluded? How does that exclusion bias results?
4. **Dependence-aware evaluation.** Overlapping horizons, cross-sectional correlation and regime clustering. How should effective N, purging/embargo lengths and the block structure for bootstrap or DSR inputs be set? A thousand scenarios are not a thousand observations.
5. **Integer allocation.** A fixed DP charge per sell day, a ₹10,000 shared book, a cash reserve, per-ISIN caps and NSE/BSE aggregation by ISIN. Give an exact enumeration or small-MIP formulation with a no-trade region, hand-worked for 3 candidates.
6. **Events with few examples.** Event time (days from results or ex-date), abnormal return against a price-only benchmark, partial pooling or shrinkage across companies, matching only on pre-outcome information.
7. **Calibration** with few resolved outcomes: scoring rule, binning, and when "probability" may be reported at all.
8. **Multiple testing.** At most 6 first-cycle candidates including cash and buy-and-hold controls. Every trial is registered. DSR/PBO inputs with so few trials.
9. **Promotion rule** for CONTINUE PAPER / REJECT / INSUFFICIENT EVIDENCE, written before any result exists.

## 6. Deliverable format

As in the prompt:
- frozen definitions;
- at most 6 candidates;
- the evaluation protocol;
- the allocation formulation;
- function signatures with hand-worked numeric test vectors;
- SEARCH_REQUESTS.

No production code. No claim that an edge exists.
