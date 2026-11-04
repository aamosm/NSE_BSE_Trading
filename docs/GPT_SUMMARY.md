# Briefing for GPT (reviewer and source researcher)

Date: 5 November 2026 (late). Repository `aamosm/NSE_BSE_Trading`, branch `cash-research-reset`.
- **Your last review:** `3513d33`.
- **Since then:** milestone 1 (`2d53906`..`19db166`), then Fable session 1 and its implementation (`15e6956`, `83bb124`, `45a956f`, the dashboard commit). `docs/HANDOFF.md` lists them.

## Your role this round

- Review `docs/FABLE_SESSION_1_SPEC.md` for mathematical errors first; then `src/marketlab/quant/` against it.
- Answer the source questions in `docs/ROADMAP.md` §4, especially the NSE base-price adjustment rule (H-CA1).
- Do not request another unchanged test-suite run; targeted tests are listed in HANDOFF.
- Never ask for credentials, statements or account data.

## What to check first (highest risk)

1. **Labels and leakage** (`quant/labels.py`, `quant/evaluate.py`): entry at open(D+1) with slippage, exit at open(D+h+1); purge by label end index plus an h-session embargo; inner fold purged; conformal residuals from the purged last 20%; holdout locked. Is any training-time quantity computed on test dates? (`features.market_stats` is fitted on training rows; rank standardization is per date.)
2. **Exchange-implied factors** (`quant/panel.py`): prev_close / prior-session close, only across true consecutive exchange sessions. Does the exclusion rule for unexplained factors (spec §2.4) make sense before the action history exists?
3. **Allocator** (`quant/allocate.py`): objective, feasibility (cash after fees, caps, K), enumeration vs neighbourhood search, exact-charge recheck. The worked example (q = 20, 0, 0; objective 14.54) is in the tests.
4. **Conformal distribution** (`quant/forecast.py`): index conventions, `P(y > c)` with the +1 correction, the vol scaling σ̂ = vol_20·√h.
5. **Economics** (spec §0): the n* derivation and the minimum-detectable-edge arithmetic.
6. **Calendar from API** (`rules/calendar.py`, `sources.load_calendar`): weekday entries as closures; `*` as special sessions; overrides; discrepancy reporting.

## Evidence (pass/fail only)

- Targeted tests: 26 hand-worked quant checks plus the synthetic-panel pipeline, calendar, research, service, app and boundary suites; all passed in their final runs.
- Real data: panel built from the two stored sessions (0 implied factors, 2 unchecked days: correct); dashboard endpoints 200 on the real folders.
- Not run: any evaluation on real history (no backfill yet), the server, the phone login.

## Known limitations (not defects to rediscover)

- No horizon is testable until the backfill; the old-format bhavcopy parser is not written.
- Dividends are omitted from labels pending H-CA1.
- Family B/C have no history; prospective collection only.
- No LLM provider is configured (owner decision); the adapter contract remains.
