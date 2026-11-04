# Active project instructions

Scope changed on 4 Nov 2026: MTF was removed and the project became a cash-only research reset. Codex produced the reset. **Claude is now the implementation owner.** GPT reviews, searches and plans. Fable is used for exactly two design and audit sessions (`docs/ROADMAP.md` §3).

Read README_FIRST.md, PROJECT_BRIEF.md, docs/IMPLEMENTATION_CONTRACT.md and docs/HANDOFF.md before editing.

## Scope

- **Packages:** the active package is `src/marketlab` and the active tests are in `tests`. `archive/phase_0_1` is the pre-reset snapshot, with known defects. Use it for reference only; never import it. Code ported from it must come with its fixes and tests.
- **Market scope:** NSE/BSE cash equities only. No MTF, borrowing, derivatives, short selling or live execution.
- **Broker access:** the app may read broker data and exchange a login request token. It has no capability to place, modify or cancel orders, convert products, use GTT, withdraw or transfer funds.
- **No live switch:** there is no live-mode configuration. Do not add a generic broker SDK client to the forecasting process.

## Credentials

- Kite app credentials (`KITE_API_KEY`, `KITE_API_SECRET`, `KITE_USER_ID`) live only in `data/private/.env`. That file is git-ignored and readable only by the Windows user.
- **Never** store a broker login password, PIN or TOTP/OTP seed, and never automate the broker login. The user logs in through the browser. `load_env` refuses such keys.
- Never print, log, commit or send secrets, tokens or account identifiers to any reviewing model.
- Committed validation records pass/fail only, never balances or holdings.

## Correctness

- Every paper proposal must pass the exchange rules engine using a dated `InstrumentSnapshot`. Unknown required status blocks.
- Do not infer a future price floor or ceiling, guaranteed appreciation or certainty from a confidence score.
- Missing data stays unknown. Publication, receipt and decision times are separate. No invented historical availability.
- Keep every experiment, including failures, with source/data/config hashes. Synthetic tests are not market backtests.
- Money uses Decimal. A score is not a probability without calibration.
- Preserve meaningful tests and add independent economic expectations. Never skip or xfail a regression to obtain a passing count.

## Operations

- Do not purchase services, publish private data or submit orders.
- End each milestone with docs/HANDOFF.md listing the actual commands, results and the exact unimplemented work.
