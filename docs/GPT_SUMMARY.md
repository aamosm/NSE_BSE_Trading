# Briefing for GPT (reviewer and planner)

Date: 4 November 2026. Repository: `aamosm/NSE_BSE_Trading`, local branch `cash-research-reset` (four commits on top of 19d12dc; **not yet pushed**). Ask the owner to push it before reviewing on GitHub.

## Your role

Review Claude's commits, answer source and fact questions, and plan between milestones. Claude implements, and you do not edit production code. Fable gets exactly two sessions (design freeze, then evidence audit); prepare their input bundles so that no Fable tokens are wasted.

## Goal and hard limits

A part-time, evidence-driven research system for NSE/BSE **cash** equities. It should eventually propose integer-share paper allocations across intraday, swing and core horizons, with recorded reasons.

Hard limits:
- Capital assumption is about ₹10,000.
- **No MTF, borrowing, derivatives, shorting or order placement.** The code has no order capability: the Kite adapter allowlists GETs plus the token exchange only.
- The owner logs in to Zerodha in the browser each day. The broker password and TOTP seed are never stored, and `load_env` refuses them.

## History

1. Claude built a sourced rules engine, metrics and a cash/MTF ledger at 19d12dc.
2. You reviewed it: NOT READY, findings R01–R10.
3. The owner removed MTF. Codex produced a cash-only reset: a read-only Kite collector, evidence store, diagnostic backtest and forecast/paper-sizing contract. The old code went to `archive/`.
4. Claude integrated the reset, verified it on the owner's Windows laptop and real account (read-only), and re-activated the cash rules engine and metrics, with fixes.

## What changed in Claude's four commits

| Commit | Change |
| --- | --- |
| `422a66c` | UPGRADE.patch applied; verified file-for-file. `.gitignore` exclusions that the patch dropped are restored |
| `452d70c` | Login redirect catcher on 127.0.0.1; Kite error-type classification; partial collection; `summary` |
| `8379b46` | Cash-only `rules/` and `metrics/` ported. **R02** status defaults are now None (unknown); **R10** Budget Sunday 1 Feb 2026 added; **R09** PBO uses midrank ties. **`paper_proposal` now abstains without a dated `InstrumentSnapshot`** and runs the entry through `evaluate_order`. `costs.py` wraps `rules.charges` |
| latest | Private `.env` credentials with an account check; detailed summary; validation regenerated on Windows; docs cleaned; ROADMAP; two Fable prompts |

R01–R10 dispositions are in `docs/RESET_REVIEW.md`:
- fixed: R02, R09, R10;
- fixed by design: R01;
- not applicable after MTF removal: R04, R05, R08;
- open for milestones F and C: R03, R06, R07.

## Evidence (pass/fail only; no account data)

- 282 tests pass, Windows, Python 3.13.7.
- Real-account read-only checks all returned: login, holdings, positions, trades, funds, NSE/BSE instrument dumps, quotes (paid data plan present), INFY daily history.
- NSE 2026 calendar equals the real INFY sessions, 22 of 22.
- HTTP smoke: `POST /orders` returns 501.
- Details are in `docs/validation/`.

## What to review first

1. `src/marketlab/research.py`: the new rules gate. Is CNC for core/swing and MIS for the intraday sleeve right? Is a missing snapshot correctly treated as abstention?
2. `src/marketlab/rules/types.py` and `engine.py`: confirm no MTF path remains and that the R02 defaults are correct.
3. `src/marketlab/cli.py`: `CallbackCatcher`, `load_env`, `auth` account check, partial collection. Check for secret-safety.
4. `src/marketlab/kite.py`: error classification must surface only the enumerated `error_type`, never provider messages.

## Planning asks

- Order and acceptance criteria for milestones A (ISIN security master), B data side (daily `InstrumentSnapshot` builder from NSE price-band and surveillance files) and C (raw/adjusted prices with corporate actions). Then a data readiness report, which feeds Fable session 1.
- Answer the search requests in `docs/ROADMAP.md` §4. The most important: are Kite daily candles corporate-action adjusted?
- Check the two Fable prompts (`prompts/02_FABLE_SESSION_1_DESIGN.txt`, `prompts/05_FABLE_SESSION_2_AUDIT.txt`) for gaps before they are spent.

## Known limitations (not defects to rediscover)

- Only the NSE 2026 calendar is loaded; BSE and 2027 dates fail closed.
- Muhurat (8 Nov 2026) is blocked: timings unknown.
- The diagnostic backtest uses next-session settlement, not the calendar.
- No ISIN master yet: symbols like RCOM / RCOM-BE differ between endpoints.
- No forecasting model, allocator, paper ledger or scenario harness yet.
