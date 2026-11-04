# Start here

**Research and data collection only. This application cannot place, modify or cancel broker orders, and cannot move funds.**

This is a cash-only NSE/BSE research base with read-only Zerodha Kite data. It is not yet a stock-selection system. There is no trained model and no demonstrated edge. `docs/ROADMAP.md` explains what is left and in what order.

## What works now (verified 4 Nov 2026 on Windows 11, Python 3.13.7)

| Capability | Behaviour |
| --- | --- |
| Kite login | Official browser login. The redirect is caught on 127.0.0.1:8766, the account is checked against `KITE_USER_ID`, and the access token is saved privately. No password is ever stored |
| Data collection | Holdings, positions, today's trades, funds, quotes and NSE/BSE instrument dumps. Endpoints refused by the plan are recorded as unavailable |
| Summary | `marketlab summary` prints holdings, funds, positions and today's trades in the terminal only |
| Historical candles | Bounded, identity-checked downloads with a metadata file of unverified factors; dataset audit |
| Exchange rules | Calendars (holidays, settlement holidays, Budget Sunday), pre-open and closing-auction sessions, tick sizes, price bands, T2T series, surveillance stages and Kite order limits, each with a cited source. Unknown inputs block |
| Fees | One cited Zerodha schedule: STT, stamp, exchange, SEBI, GST, DP |
| Paper gate | Forecast contract plus a one-entry, integer-share proposal. It must pass the rules engine, and abstains without a dated security snapshot |
| Metrics | Time-weighted return, XIRR, drawdowns, Sharpe (risk-free rate required), Sortino, PSR, DSR, PBO, trade and cost statistics |
| Evidence store | Append-only SQLite with publication/receipt times, deduplication, quota and backups. RSS news is stored as unreviewed evidence |
| Backtest | One-instrument diagnostic baselines (cash, buy-and-hold, trend). Not a strategy |
| Status page | Loopback-only and read-only. Order routes return 501 |

**Not built yet:**
- ISIN security master;
- daily rule-input builder;
- corporate actions;
- forecasting models;
- multi-stock allocator;
- cash paper ledger and reconciliation;
- engineering scenario harness;
- real dashboard and Android app.

## Daily use (PowerShell, in this folder)

```powershell
.\.venv\Scripts\python.exe -m marketlab auth        # log in to Zerodha in the browser that opens (once a day)
.\.venv\Scripts\python.exe -m marketlab collect --instruments
.\.venv\Scripts\python.exe -m marketlab summary
.\.venv\Scripts\python.exe -m marketlab dashboard   # http://127.0.0.1:8765
```

First-time setup on a new machine: `py -3.13 -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -e .` and `-r requirements-dev.lock`, then `.\.venv\Scripts\python.exe -m pytest` (282 tests). Put the Kite app credentials in `data/private/.env` (see `docs/KITE_AND_SERVER_SETUP.md`). Never put the broker password there; the program refuses it.

## Who does what next

1. **Claude:** data milestones A–C and a data readiness report (`docs/ROADMAP.md` §2, `prompts/01_CLAUDE_ENGINEERING.txt`).
2. **GPT:** reviews each milestone (`prompts/04_INDEPENDENT_REVIEW.txt`), handles source searches and planning. Briefing: `docs/GPT_SUMMARY.md`.
3. **Fable, session 1:** research design freeze (`prompts/02_FABLE_SESSION_1_DESIGN.txt`).
4. **Claude:** implements that design. **GPT:** validates it (`prompts/03_VALIDATION.txt`). Then paper observation.
5. **Fable, session 2:** evidence audit (`prompts/05_FABLE_SESSION_2_AUDIT.txt`).

A passing test suite is not permission to trade. There is no live switch.

## Where things are

| Item | Location |
| --- | --- |
| Current state and commands | `docs/HANDOFF.md` |
| Plan, remaining items and Fable usage | `docs/ROADMAP.md` |
| Rules and sources | `docs/RULES_REGISTER.md` |
| Previous review and how each finding was handled | `docs/reviews/PHASE_0_1_REVIEW.md`, `docs/RESET_REVIEW.md` |
| Fresh validation output | `docs/validation/` |
| Pre-reset project (history only, not imported) | `archive/phase_0_1` |
