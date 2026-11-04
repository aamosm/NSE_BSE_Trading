# Briefing for GPT (reviewer and source researcher)

Date: 5 November 2026. Repository `aamosm/NSE_BSE_Trading`, branch `cash-research-reset`.
- **Your last review:** `3513d33`.
- **This milestone:** commits `2d53906` through the docs commit at the head of the branch (`docs/HANDOFF.md` lists every SHA).
- **Push status:** the owner decides when to push; review on GitHub once it is pushed.

## Your role this round

- Review the new commits and the five small documents:
  - `HANDOFF.md`;
  - `DATA_READINESS.md`;
  - `SOURCE_STATUS.md`;
  - `DEPLOYMENT.md`;
  - `FABLE_HANDOFF.md`.
- Answer the source questions in `docs/ROADMAP.md` §4.
- Do **not** request another unchanged test-suite run: Claude ran targeted tests per change (listed in HANDOFF).
- Never ask for credentials, statements or account data.

## Scope (unchanged limits, new hosting)

- **Market:** cash-only NSE/BSE equities, read-only Kite, simulated execution only. No MTF, borrowing, shorting, derivatives, orders or live toggle.
- **Hosting:** one private Linux server (prepared, not yet rented) and a phone PWA over Tailscale.
- **Login:** stays manual. The owner logs in on Zerodha's page from the phone each trading day.

## What to review first (highest risk)

1. **Login callback:** `src/marketlab/login.py`, `webapp.py` (`_login_start`, `_callback`), `cli.py` (`CallbackCatcher`, `auth`).
   - State uses `redirect_params`, is stored hashed, single-use, 10 minutes, at most 5 pending.
   - The path must equal `KITE_REDIRECT_URL`'s path exactly. One value per parameter; `status=success`.
   - The account check is mandatory. Request lines are never logged.
   - Is anything missing for a redirect that arrives on the phone through Tailscale Serve?
2. **Snapshot chronology:** `store.py` (`latest`, batches), `account.py`.
   - A→B→A, a kind missing from the newest batch, an incomplete batch, trade-book session attribution (after `session_open`), unknown numbers.
3. **Point-in-time rule inputs:** `master.py`.
   - Series for session D come from the previous day's after-close `sec_list` and `REG1_IND` (observed: 3/3 series changes agree).
   - `Status=S` → suspended and `ICA≠100` → call auction are labelled ASSUMPTION. Please find NSE's field definitions.
4. **Costs:** `rules/charges.day_charges`. Is the aggregation (exchange, ISIN, date, kind, side; average price to the paisa; rupee rounding) right under the **final** STT rules?
5. **Scheduler failure behaviour:** `service.py`. Due windows, breaker back-off, AUTH_REQUIRED on an invalidated token, idempotent WAIT decisions, alert/heartbeat content.
6. **Deployment:** `deploy/*`, `docs/DEPLOYMENT.md`. Hardening, secrets procedure, Tailscale Serve (not Funnel), redirect registration order, backup/restore, rollback.

## Evidence (pass/fail only)

- **Targeted tests:** 148 new tests in 8 files plus the affected existing suites. 435 tests are collected in total; the unchanged ones were not re-run for a count.
- **Real data, read-only:**
  - 15 official sources retrieved and catalogued;
  - security master for 5 Nov (2,627 NSE / 5,044 BSE listings, 0 ISIN conflicts);
  - real snapshots through the engine: GSM-2 fresh buy blocked, ESM-1 BE delivery accepted with a warning;
  - NSE 2026 holidays and settlement holidays agree with NSE's APIs;
  - one Kite batch COLLECTED; a pre-open trade book is labelled SESSION_UNKNOWN.
- **App:** smoke-tested on loopback.
- **Restore:** SQLite backup → archive → restore → `integrity_check` ok.
- **Not run:** any server step, phone login over Tailscale, age encryption, contract-note reconciliation, corporate-action reconciliation.

## Known limitations (not defects to rediscover)

- No historical backfill yet, so no horizon is testable (`DATA_READINESS.md`).
- No official corporate-action history; Kite history is provider-adjusted.
- BSE calendar unverified; 2027 calendar not loaded; MIS list unavailable; Zerodha's MIS square-off time on Muhurat unknown.
- No model, allocator, paper ledger or replay harness. Every decision is WAIT / MODEL_NOT_VALIDATED.
- Exchange website terms of use not yet reviewed.
