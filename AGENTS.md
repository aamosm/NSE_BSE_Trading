# Active project instructions

**Scope (revised 4–5 Nov 2026, consolidated handoff):** a cash-only NSE/BSE research and **paper-investing** system.
- It runs on one small private Linux server, with an installable private phone app (PWA) over Tailscale.
- **Claude** is the implementation owner.
- **GPT** reviews, researches sources and plans.
- **Fable** is used for exactly two sessions, design freeze and evidence audit (`docs/ROADMAP.md` §3).

Read README_FIRST.md, docs/HANDOFF.md, docs/ROADMAP.md and docs/IMPLEMENTATION_CONTRACT.md before editing.

## Scope

- **Packages:** the active package is `src/marketlab` and the active tests are in `tests`. `archive/phase_0_1` is the pre-reset snapshot, with known defects. Use it for reference only; never import it.
- **Market scope:** NSE/BSE cash equities only. No MTF, borrowing, derivatives, short selling or real orders. Execution is always simulated (REPLAY and FORWARD_PAPER adapters, neither with order capability).
- **Broker access:** the app may read broker data and exchange a login request token. It has no capability to place, modify or cancel orders, convert products, use GTT, withdraw or transfer funds.
- **No live switch:** there is no live-mode configuration and none may be added. A future live system needs its own explicit project decision. Never give the forecasting or model layer a general broker SDK client. A test enforces that research, rules, metrics, costs and account modules import no broker or network library.
- **Hosting:** the server runs the scheduler and the app as an unprivileged user.
  - The app binds 127.0.0.1 only and is reached through Tailscale Serve.
  - Never expose it publicly; no Funnel, no open port.
  - Deploy only pinned, reviewed commits (`deploy/install_release.sh`). Never deploy automatically.

## Credentials and login

- Kite app credentials (`KITE_API_KEY`, `KITE_API_SECRET`, `KITE_USER_ID`, `KITE_REDIRECT_URL`) live only in the private `.env` on the machine that uses them. It is git-ignored, mode 0600 / user-only ACL, and typed there by the owner.
- **Never** store a broker login password, PIN, OTP/TOTP seed or browser cookie, and never automate the broker login.
  - The owner logs in daily on Zerodha's own page from the phone app (or `marketlab auth` on the laptop).
  - The env loader accepts only allowlisted keys and refuses names containing PASSWORD, PASSWD, PIN, TOTP or OTP.
- Login state is single-use and expiring. The callback path must match the registered redirect exactly. The account must equal `KITE_USER_ID`.
- Never print, log, commit or send secrets, tokens, request tokens or account identifiers to any reviewing model. Request lines are never logged.
- Committed validation records pass/fail only, never balances or holdings.

## Correctness

- Every paper proposal must pass the exchange rules engine using a dated `InstrumentSnapshot` built from point-in-time inputs. Unknown required status blocks.
- The current account state comes from the latest **completed** collection batch. A missing, stale or malformed value is unknown, never zero.
- Keep provider-adjusted prices (Kite history), actual exchange prices and derived series apart. Never apply a corporate action twice.
- Do not infer a future price floor or ceiling, guaranteed appreciation or certainty from a confidence score.
- Missing data stays unknown. Publication, receipt, effective and decision times are separate. No invented historical availability.
- Keep every experiment, including failures, with source/data/config hashes. Synthetic tests are not market backtests.
- Money uses Decimal. A score is not a probability without calibration.
- Preserve meaningful tests and add independent economic expectations. Never skip or xfail a regression to obtain a passing count.
- Validate changes with targeted tests. Do not re-run unchanged suites just to report a count.

## Operations

- Do not purchase services, publish private data or submit orders. Recurring services are the owner's decision; each needs a stated purpose and budget (`docs/DEPLOYMENT.md` §2).
- Exchange files: official hosts only, at most one request per file per day, no anti-bot bypass. Record refused retrievals instead of guessing endpoints.
- No paid runtime LLM calls unless the owner sets a spending cap and a usage ledger exists. Never use an LLM for arithmetic or dashboard wording.
- End each milestone with docs/HANDOFF.md listing the actual commands, results, exact commits and the exact unimplemented work.
