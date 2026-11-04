# Start here

**Research and paper decisions only. This application cannot place, modify or cancel broker orders, and cannot move funds.**

A cash-only NSE/BSE research system: read-only Zerodha Kite data, official exchange files, a scheduler, a quantitative core that follows a frozen design (`docs/FABLE_SESSION_1_SPEC.md`), and a private dashboard. It is **not yet a stock-selection system**: no candidate has passed the promotion rule, so every decision is WAIT. The design says why that is the expected answer at ₹10,000 of capital.

## What works now (verified 5 Nov 2026 on Windows 11, Python 3.13.7)

| Capability | Behaviour |
| --- | --- |
| Kite login | Zerodha's own page, single-use state, exact callback path, account check; only the access token is saved |
| Account data | Batches; the view uses the latest completed batch; unknown stays unknown |
| Exchange files | 15 official NSE/BSE sources collected politely and catalogued; calendar years loaded from NSE's holiday APIs |
| Daily rule inputs | Security master and `InstrumentSnapshot` per symbol and session with provenance |
| Exchange rules | Calendars, Muhurat table, sessions, ticks, bands, T2T, surveillance, Kite limits; unknown inputs block |
| Costs | Zerodha schedule with STT per security-day rounded to the rupee; DP per ISIN per sell day |
| Price panel | Actual prices from bhavcopies with exchange-implied corporate-action factors (`panel-build`) |
| Universe | Dated screen: EQ, no ETFs, liquidity, price, surveillance, bands (`screen`) |
| Forecasts | Cross-sectional ridge with split-conformal distributions and shrinkage; abstains without calibration |
| Allocation | Integer, fixed-cost-aware, half-Kelly risk; exit policy with hysteresis |
| Evaluation | Purged walk-forward with embargo and a locked holdout; calibration metrics; paper simulation with exact charges; promotion rule (`evaluate`) |
| Scheduler | Calendar-driven jobs, health states, breakers, catch-up, request execution (`run`) |
| Dashboard | Overview, Data, Universe, Forecasts, Evaluation, Research, Controls at `http://127.0.0.1:8765` |

**Not done yet:** the historical backfill (so no forecast can be fitted today), corporate-action verification, event history for family B, the paper ledger, the server.

## Daily use on the laptop (PowerShell, in this folder)

```powershell
.\.venv\Scripts\python.exe -m marketlab auth                        # log in to Zerodha once a day
.\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY      # scheduler (leave running)
.\.venv\Scripts\python.exe -m marketlab dashboard                   # http://127.0.0.1:8765
```

Everything else (fetching files, building the panel, screening, evaluating, deciding) can be requested from the dashboard's Controls tab or run by command (`docs/HANDOFF.md`).

## Who does what next

1. **Lower-cost implementation models:** the historical backfill, the H-CA1 check, the registered trials, the event registry, the paper ledger (`docs/ROADMAP.md` §2).
2. **Owner:** daily login; policy in Controls; server when ready; revoke the exposed keys.
3. **GPT:** review the new commits with `docs/GPT_SUMMARY.md`; answer the source questions.
4. **Fable, session 2:** the audit, after paper observation.

A passing test suite is not permission to trade. There is no live switch.

## Where things are

| Item | Location |
| --- | --- |
| Design (frozen) | `docs/FABLE_SESSION_1_SPEC.md` |
| Current state, commits, next work | `docs/HANDOFF.md` |
| Plan | `docs/ROADMAP.md` |
| Data coverage and sources | `docs/DATA_READINESS.md`, `docs/SOURCE_STATUS.md` |
| Server and phone setup | `docs/DEPLOYMENT.md` |
| Rules and sources | `docs/RULES_REGISTER.md` |
| Pre-reset project (history only) | `archive/phase_0_1` |
