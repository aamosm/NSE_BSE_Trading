# Handoff

Updated 4 November 2026 by Claude (implementation owner). Branch `cash-research-reset`, local only. GitHub `main` is still the old phase-1 commit 19d12dc. No account identifiers, tokens or balances appear in this file.

## Scope

Cash-only NSE/BSE research with read-only Kite data. MTF, borrowing, derivatives, short selling and order placement are out of scope, and no code path for them exists. The laptop is the "server" until the project is finished.

## Commits on this branch

| Commit | What |
| --- | --- |
| `422a66c` | Reset to the v0.2.0 cash research base (UPGRADE.patch on 19d12dc). Verified file-for-file against the delivered folder; the archive matches upstream 61/61. Restored the dropped `.gitignore` exclusions |
| `452d70c` | Kite login usability: redirect caught on 127.0.0.1:8766; Kite error types classified (TokenException / PermissionException / InputException); collection continues past plan-limited endpoints; `summary` command |
| `8379b46` | Cash-only rules engine and metrics ported from the archive. Review fixes R02, R09, R10. Paper proposals gated on the rules engine. One fee implementation |
| (latest) | Credentials from private env file, account check on login, detailed summary, validation regenerated on Windows, docs cleaned, ROADMAP and GPT summary, two Fable session prompts |

## Verified on this laptop (Windows 11, Python 3.13.7)

- **Tests:** 282 passed, 0 failed, 0 skipped. Output in `docs/validation/tests.txt`.
- **Synthetic checks:**
  - demo;
  - news fixture import;
  - dataset audit;
  - HTTP smoke: `/` and `/health` return 200, a path-traversal attempt returns 404, `POST /orders` returns 501;
  - `compileall`.
- **Real account, read-only** (`docs/validation/real_account_readonly.txt`):
  - official browser login, with the account matched to `KITE_USER_ID`;
  - holdings, positions, trades and funds all returned;
  - NSE and BSE instrument dumps returned;
  - quotes returned, so the paid data entitlement is present;
  - INFY daily history: 22 bars, with metadata and audit;
  - **calendar cross-check: 22 of 22 real sessions (1 Oct–3 Nov 2026) match `MarketCalendar`.**
- **Not run:** any order action. None exists.

## Credentials (policy)

- `data/private/.env` holds `KITE_API_KEY`, `KITE_API_SECRET` and `KITE_USER_ID`. It is git-ignored, and the folder ACL is restricted to the Windows user.
- `auth` reads it and never saves the secret elsewhere. `load_env` **refuses** any `*PASSWORD*`, `*PIN*` or `*OTP*`/`*TOTP*` key.
- The broker login password is never stored. Login is always done by the user in the browser, about once a day, because tokens expire at 06:00.
- `data/private/kite_session.json` holds the daily access token.

## Commands

```powershell
.\.venv\Scripts\python.exe -m marketlab auth          # opens Zerodha login; you log in; session saved
.\.venv\Scripts\python.exe -m marketlab collect --instruments --symbols NSE:INFY
.\.venv\Scripts\python.exe -m marketlab summary       # holdings, funds, positions, today's trades
.\.venv\Scripts\python.exe -m marketlab dashboard     # http://127.0.0.1:8765, read-only status page
.\.venv\Scripts\python.exe -m pytest                  # 282 tests
```

## Review findings R01–R10

See `docs/RESET_REVIEW.md`.
- Fixed: R02, R09, R10.
- Fixed by design: R01.
- Not applicable after MTF removal: R04, R05, R08.
- Open for future milestones: R03 and R06 (cash paper ledger, milestone F), R07 (corporate actions, milestone C).

## Known limitations

- **Calendars:** only NSE 2026 is loaded. BSE dates and any 2027 date are refused (fail-closed). Muhurat (8 Nov 2026) is blocked because its timings are unknown.
- **Diagnostic backtest:** single-instrument. It approximates settlement as the next session in the data rather than using `MarketCalendar.settlement_date`.
- **Daily rules inputs:** `InstrumentSnapshot` must currently be built by hand. There is no daily builder yet for series, price bands, surveillance lists or F&O membership (milestone B data side).
- **Kite history:** whether candles are corporate-action adjusted has not been verified (see ROADMAP §4).
- **Account data:** symbols such as RCOM vs RCOM-BE differ between trades and positions. Joins must be keyed by ISIN (milestone A).

## Next task

See `docs/ROADMAP.md` §2. Claude builds milestones A, B (data side) and C, then a real dataset readiness report. Then **Fable session 1** (`prompts/02_FABLE_SESSION_1_DESIGN.txt`). GPT reviews each milestone with `prompts/04_INDEPENDENT_REVIEW.txt`; `docs/GPT_SUMMARY.md` is its briefing.
