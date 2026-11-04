# Architecture decisions

Each decision has a status: **Accepted** (in force), **Planned** (accepted direction, not built) or **Open** (needs the user or evidence). They follow Build Guide §6 and the reference review (`docs/REFERENCE_REVIEW.md`).

| ID | Decision | Status | Reason / evidence |
| --- | --- | --- | --- |
| AD-01 | **Python 3.13 backend; standard-library-only domain core.** Rules, ledger and metrics import nothing outside the stdlib. FastAPI/Pydantic only at the HTTP boundary (Phase 6/8) | Accepted | Smallest dependency surface where correctness matters; runs on this Windows machine without extra installs |
| AD-02 | **Money is `Decimal` rupees; quantities are integer shares.** Rounding to the paisa (half-up) happens only at a charge or ledger posting, and is documented per component. Broker floats are converted with `Decimal(str(x))` at the adapter | Accepted | Contract; reference flaw F13 |
| AD-03 | **Time is timezone-aware, displayed in IST (fixed +05:30).** Domain code never calls `datetime.now()`; a clock is injected (replay, paper, live) | Accepted | Replay must be deterministic (flaw F4: OpenAlgo's wall-clock settlement) |
| AD-04 | **Separate pluggable models:** legality (`rules.engine`), costs (`rules.charges`), calendar/settlement (`rules.calendar`), financing (`ledger` MTF), fills (Phase 3). Each is effective-dated and cites sources | Accepted | Lean's model split is the right shape; its India numbers are wrong (F2) |
| AD-05 | **Double-entry, append-only ledger.** Every economic event is a balanced journal entry, and corrections are new entries. Valuation marks are kept apart from cash flows. Charges are expensed per order/day, never buried in cost basis, so costs are visible separately from returns | Accepted (Phase 1) | Contract "Cash and financing ledger"; Brief "separate costs from returns" |
| AD-06 | **Event-sourced state.** Book state is a pure function of an ordered event log (deposits, fills, marks, margin changes, corporate actions). Events carry IDs, and duplicates are ignored. Phase 1 keeps the log as JSON fixtures in memory; Phase 3 persists it | Accepted (Phase 1) | Restart and duplicate-event requirements; replay of decisions |
| AD-07 | **PostgreSQL for durable operational state** (events, intents, orders, fills, ledger), from Phase 3. Run locally from a pinned `postgres` Docker image (Docker 29.7 is installed; no local psql). SQLAlchemy + Alembic migrations. SQLite is not used for money | Planned | Guide §6. Needed for transactional intent-before-submit (F10) |
| AD-08 | **Research storage: Parquet files queried with DuckDB,** immutable inputs keyed by content hash, PIT tables with publication time and revision links (qlib-style) | Planned (Phase 2) | Guide §6; reference qlib PIT design |
| AD-09 | **One execution owner.** A single worker holds a lease with a fencing token and is the only process allowed to submit orders. Research and backtests run as separate, budgeted processes and can never call order methods | Planned (Phase 3/8) | Contract "Execution and recovery"; OpenAlgo shows the race bugs a multi-trigger design invites |
| AD-10 | **Order lifecycle with an `UNCERTAIN` state.** Persist the intent, then submit with a ≤20-character tag, then reconcile. A lost acknowledgement leads to a search by tag and order book, never a resend. Fills are deduplicated by exchange trade ID and cumulative quantity. Position mismatches lock the instrument | Planned (Phase 3) | Hummingbot/nautilus/pysystemtrade ideas; avoid freqtrade F10/F11 |
| AD-11 | **Broker adapter wraps the official `pykiteconnect`.** Read-only mode removes order methods from the adapter object (not just the UI). `debug` is never enabled; logs pass through a redaction filter with tests. Login is the official interactive flow; no TOTP seed, no cookies | Planned (Phase 7) | F12; AGENTS.md security rules |
| AD-12 | **UI: React + TypeScript (Vite) responsive web app;** Capacitor wraps it for Android. The phone app only displays and approves. No secrets in the APK | Planned (Phase 6/9) | Guide §6, §13 |
| AD-13 | **Deployment: Docker Compose on one small Linux VM with a static public IP** (Kite order placement requires a registered static IP) | Planned (Phase 8). Purchase needs user approval | Guide §13; RULES_REGISTER §9 |
| AD-14 | **Metrics definitions are preregistered** in `docs/METRICS.md`. Annualisation comes from the loaded calendar, and the risk-free rate is always explicit | Accepted | F8, F9 |
| AD-15 | **Reference projects are studied, never vendored.** No code is copied from GPL/AGPL/unlicensed projects. Any future dependency is pinned, licence-checked and wrapped by contract tests | Accepted | Guide §15; licences in REFERENCE_REVIEW §1 |
| AD-16 | **LLMs at runtime only extract evidence into strict schemas;** no credentials, order tools, shell or policy writes | Accepted | AGENTS.md "Model boundaries" |
| AD-17 | **Live data and broker products:** Kite Connect (₹500/month) for quotes and historical candles versus the free personal API | Open | User decision at Phase 7; not needed before then |
| AD-18 | **Hosting provider and budget** | Open | User decision at Phase 8 |

## Module map (current and planned)

```
src/marketlab/
  rules/      Phase 0  legality, sessions, calendars, ticks, bands, series, surveillance, charges, MTF entry rules
  metrics/    Phase 0  returns, risk, selection bias, trade and cost metrics
  ledger/     Phase 1  journal, lots, cash/MTF book, interest, corporate actions, replay
  data/       Phase 2  PIT ingestion, snapshots (InstrumentSnapshot builders)
  execution/  Phase 3  intents, simulated broker, fill models, reconciliation
  strategy/   Phase 4  forecasts, allocator, risk
  research/   Phase 5  scenario and trial harness
  api/        Phase 6  FastAPI service for the dashboard
  broker/     Phase 7  Kite adapter (read-only first)
```
