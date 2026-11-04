# Current handoff

Status: Phase 0 in progress. The rules register and rules engine are done; the remaining Phase 0 documents are not.

Do not place tokens, account identifiers or raw private statements in this handoff.

- **Phase and scoped objective:** Phase 0, with the user's priority "get the stock rules right before Zerodha integration". Built a sourced, effective-dated rules engine for NSE/BSE cash equities at Zerodha, plus its register.
- **Implementation owner:** Claude Code.
- **Starting and ending commit:** none. The folder is not yet a Git repository. `.gitignore` already excludes `.venv/`, secrets and raw data.
- **Files changed and why:**
  - `pyproject.toml`, `requirements-dev.lock`: package and pinned test dependencies.
  - `src/marketlab/rules/`:
    - `provenance.py`: source registry and status levels.
    - `types.py`, `calendar.py`, `sessions.py`, `ticks.py`, `bands.py`, `instruments.py`: series, groups and surveillance.
    - `charges.py`, `mtf.py`, `broker.py`: MIS cut-offs, Kite API limits, rate limiter.
    - `engine.py`: `evaluate_order`.
    - `demo.py`.
  - `tests/`: 159 tests, with hand-worked expected values, property tests and provenance-integrity tests.
  - `docs/RULES_REGISTER.md`, `docs/ENVIRONMENT.md`, this file.
- **Commands actually run:**
  - `python -m venv .venv`, then `pip install pytest==9.2.0 hypothesis==6.170.14`.
  - `.venv\Scripts\python -m pytest` → **159 passed, 0 failed, 0 skipped**.
  - `python -m marketlab.rules.demo`.
  - A mutation check: 7 deliberate rule errors in a scratch copy, each caught by at least one test. They were: tick slab, band rounding, settlement holiday, T2T same-day sale, CAS start date, GST base, and the low-price MPP floor.
- **Test results:** 159 executed, 159 passed, 0 failed, 0 skipped. The JSON registries (1,200 scenarios, 1,000 trials) remain **PLANNED** and were not run.
- **Assumptions and primary sources checked:**
  - Read directly: NSE consolidated circular NSE/CMTR/73927 (28 Apr 2026), plus later NSE/SEBI circulars on CAS (3 Aug 2026), the revised pre-open (7 Sep 2026), revised IBC (10 Aug 2026), GSM, ESM, tick size, algo market orders, and 2026 settlement holidays.
  - Also read Zerodha's charges, MTF, CAS, MIS, surveillance, T2T and API pages.
  - Every rule is tagged PRIMARY, BROKER_OFFICIAL, SECONDARY, CONFLICTING, ASSUMPTION or UNKNOWN. Open items are in RULES_REGISTER.md section 10.
- **MTF/accounting implications:**
  - Entry rules are encoded: approved list, DDPI, margin = VaR + 3×/5×ELM, exposure caps and surveillance blocks.
  - Interest day-count and sale-day treatment are **UNKNOWN**. They must be verified against Zerodha's MTF ledger entries before the Phase 1 fixtures are final.
  - Charge rounding is an ASSUMPTION pending contract-note reconciliation.
- **Data/lookahead implications:**
  - The engine requires a point-in-time `InstrumentSnapshot` dated the same day as the order. A stale snapshot blocks.
  - Unloaded calendars, surveillance lists and tick sizes block.
  - Replay over history needs historical calendars and surveillance/series history. Broker rules applied to past dates raise a counterfactual warning.
- **Known defects and blockers:**
  - Only the NSE 2026 calendar is loaded, so BSE orders and 2027 dates block.
  - Special sessions (Muhurat on 8 Nov 2026, IPO day, call auction) are blocked, not modelled.
  - Short-delivery auctions are documented but not simulated (Phase 3).
- **Reviewer findings addressed or outstanding:** none yet. Ready for GPT review with `prompts/REVIEW.txt`, focused on RULES_REGISTER.md and `engine.py`.
- **Budget used and any proposed new expense:** none. No API keys, purchases or broker connections.
- **Exact next task:**
  1. Finish the rest of Phase 0: `docs/ARCHITECTURE_DECISIONS.md`, `docs/DATA_INVENTORY.md` (including the daily inputs the engine needs: security file, surveillance lists, F&O list, MTF/MIS lists, VaR/ELM) and `docs/PHASE_1_PLAN.md`.
  2. Run `git init` and make the first commit.
  3. Resolve the account-specific open items in RULES_REGISTER.md section 10 (the T2T next-day sale, MTF interest day-count and DDPI status) from the user's own Zerodha account and statements.
