# Start here

**Research and paper decisions only. This application cannot place, modify or cancel broker orders, and cannot move funds.**

This is a cash-only NSE/BSE research system with read-only Zerodha Kite data, official exchange files, a scheduler and a private phone app. It is **not yet a stock-selection system**: no model has been fitted or validated, and every decision it records is WAIT. `docs/ROADMAP.md` explains what is left and in what order.

## What works now (verified 5 Nov 2026 on Windows 11, Python 3.13.7)

| Capability | Behaviour |
| --- | --- |
| Kite login | Zerodha's own login page, with a single-use 10-minute state and an exact callback path. The account must be `KITE_USER_ID`; only the access token is saved. Works from the terminal now, and from the phone app once the server is up |
| Account data | Holdings, positions, trades and funds are collected in batches. The view uses the latest **completed** batch. Unknown values stay unknown; a trade book is never shown as today's unless it is |
| Exchange files | 15 official NSE/BSE sources: master, bhavcopies, bands, surveillance, F&O, index closes, holidays and RSS. Collected politely, compressed, every attempt catalogued (`docs/SOURCE_STATUS.md`) |
| Daily rule inputs | Security master and `InstrumentSnapshot` per symbol and session, from point-in-time files, with per-field provenance |
| Exchange rules | Calendars verified against NSE's APIs, the Muhurat 8 Nov 2026 table, sessions, ticks, bands, T2T, surveillance and Kite limits. Unknown inputs block |
| Costs | Zerodha schedule; STT per security-day rounded to the rupee; DP reconciled from the funds statement; stamp allocation flagged unresolved |
| Corporate actions | Kite-adjusted, actual exchange and derived price series kept apart; double adjustment refused |
| Scheduler | `marketlab run`: calendar-driven jobs, RUNNING / AUTH_REQUIRED / DEGRADED states, circuit breakers, analysis pause, optional heartbeat and alerts |
| Phone app | Installable private PWA: health, data age, login button, pause control, **actual** vs **simulated** accounts, decision timeline, upcoming corporate actions and listings, blockers, costs |
| Deployment | systemd units, provisioning, pinned release/rollback and encrypted backups (`docs/DEPLOYMENT.md`). **Not yet run on a server** |
| Metrics, backtest | PSR/DSR/PBO, returns and drawdowns; a one-instrument diagnostic backtest (not a strategy) |

**Not built yet:**
- backfill of historical exchange files;
- official corporate-action history;
- financial filings;
- forecasting models;
- multi-stock allocator;
- simulated cash ledger;
- replay harness;
- BSE calendar.

## Daily use on the laptop (PowerShell, in this folder)

```powershell
.\.venv\Scripts\python.exe -m marketlab auth                         # log in to Zerodha once a day
.\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY       # scheduler (leave running)
.\.venv\Scripts\python.exe -m marketlab dashboard                    # app at http://127.0.0.1:8765
.\.venv\Scripts\python.exe -m marketlab summary                      # terminal view of the account
```

First-time setup: see `docs/KITE_AND_SERVER_SETUP.md`. Server and phone: `docs/DEPLOYMENT.md`.

## Who does what next

1. **Claude:** backfill historical files, corporate-action history and the first earnings-event data path (`docs/ROADMAP.md` §2).
2. **Owner:** rent the server and complete `docs/DEPLOYMENT.md` §3. Log in from the phone on trading days. Optionally provide one contract note and funds statement for local cost reconciliation.
3. **GPT:** review the new commits with `docs/GPT_SUMMARY.md`; answer source questions.
4. **Fable, session 1:** only after the backfill, with `docs/FABLE_HANDOFF.md`.

A passing test suite is not permission to trade. There is no live switch.

## Where things are

| Item | Location |
| --- | --- |
| Current state, commits, setup actions | `docs/HANDOFF.md` |
| Plan | `docs/ROADMAP.md` |
| Data coverage and blockers | `docs/DATA_READINESS.md` |
| Sources and retrieval results | `docs/SOURCE_STATUS.md` |
| Server and phone setup | `docs/DEPLOYMENT.md` |
| Fable session 1 input | `docs/FABLE_HANDOFF.md` |
| Rules and sources | `docs/RULES_REGISTER.md` |
| Review findings and dispositions | `docs/RESET_REVIEW.md` |
| Pre-reset project (history only, not imported) | `archive/phase_0_1` |
