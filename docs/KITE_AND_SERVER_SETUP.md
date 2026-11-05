# Kite and laptop setup

This guide connects DATA only. The application has no order, conversion, GTT or fund-transfer endpoint.

It covers the Windows laptop, which is used until the server exists. **For the server and the phone app, use `docs/DEPLOYMENT.md`.**

## A. Install (Windows, PowerShell, in the project folder)

    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock

The runtime uses only the Python standard library. The lock file pins the test tools.

## B. Kite developer app and private env file

1. Create the app at https://developers.kite.trade/. Quotes and historical candles need the paid Kite Connect plan (₹500/month per API key). This account has it.
2. The redirect URL registered today is `http://127.0.0.1:8766/`. A Kite app has **one** redirect URL. When the server is ready it changes to `https://marketlab.<tailnet>.ts.net/kite/callback` (`DEPLOYMENT.md` §3.7).
3. Create `data/private/.env`. Both `data/private/` and `.env*` are git-ignored.

       KITE_API_KEY=your_api_key
       KITE_API_SECRET=your_api_secret
       KITE_USER_ID=your_client_id
       # optional; must equal the registered redirect URL exactly
       KITE_REDIRECT_URL=http://127.0.0.1:8766/

Only the keys listed in `deploy/env.example` are accepted. Any key whose name contains PASSWORD, PASSWD, PIN, TOTP or OTP is refused, as is any unknown key. The program cannot detect a password typed as the *value* of an allowed key, so never do that.

Restrict the folder to your Windows user:

    icacls data\private /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"
    Get-ChildItem -Force data\private | ForEach-Object { icacls $_.FullName /reset }

`data/private/kite_app.json` from earlier versions is no longer read. You may delete it.

## C. Daily login (laptop)

    .\.venv\Scripts\python.exe -m marketlab auth

1. The program opens Zerodha's login page with a random single-use **state**, valid 10 minutes.
2. You type your password and app code on Zerodha's page. The program never sees them.
3. The program listens on the registered loopback address. It accepts only the exact registered path, carrying that state and a well-formed request token.
4. It exchanges the token, requires the account to be `KITE_USER_ID`, and saves only the access token.

If nothing arrives within `--wait` seconds (default 300), paste the full redirected URL from the address bar into the hidden prompt. It is checked the same way.

Tokens expire at the **next 06:00 IST** and can be invalidated earlier, so log in once each collection day. Logging in is never automated.

## D. Collection, scheduler and app (laptop)

    .\.venv\Scripts\python.exe -m marketlab collect --instruments --symbols NSE:INFY    # one read-only batch
    .\.venv\Scripts\python.exe -m marketlab summary                                     # terminal view of the latest batch
    .\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY NSE:TCS              # scheduler; leave it running
    .\.venv\Scripts\python.exe -m marketlab dashboard                                   # app at http://127.0.0.1:8765
    .\.venv\Scripts\python.exe -m marketlab pause                                       # pause paper analysis (or resume)

**Collection batches.** Each collection is one batch. An endpoint the plan refuses is recorded as unavailable, and an expired session stops the batch, which is then ignored. Account views always use the latest **completed** batch:
- missing or malformed values show as unknown, never zero;
- a trade book read before the session opens is labelled with an unknown day.

**Scheduler (`run`).** It follows the exchange calendar (`DEPLOYMENT.md` §1). When the Kite session is missing or invalidated it shows AUTH_REQUIRED, and exchange-file collection continues.

## E. Official exchange files

    .\.venv\Scripts\python.exe -m marketlab fetch-public --date 2026-11-04            # one trading date (idempotent)
    .\.venv\Scripts\python.exe -m marketlab build-master --date 2026-11-05            # security master for a session
    .\.venv\Scripts\python.exe -m marketlab snapshot --date 2026-11-05 --symbol INFY  # rules input + provenance
    .\.venv\Scripts\python.exe -m marketlab verify-calendar --year 2026               # engine vs NSE holiday APIs

Files are stored compressed under `data/market/raw/`, and every attempt is recorded in `data/market/catalog.sqlite3`. See `docs/SOURCE_STATUS.md`.

## E2. Price panel, universe, evaluation (the quant core)

    .\.venv\Scripts\python.exe -m marketlab panel-build                                     # actual prices from stored bhavcopies
    .\.venv\Scripts\python.exe -m marketlab screen --date 2026-11-04                        # universe for decisions after that close
    .\.venv\Scripts\python.exe -m marketlab freeze-holdout                                  # ONCE, after the backfill; never moves
    .\.venv\Scripts\python.exe -m marketlab evaluate --candidate A --h 20                   # registered trial on the development view
    .\.venv\Scripts\python.exe -m marketlab decide                                          # saved candidate/horizon/policy; prints the decision id

- `evaluate` refuses to run until the holdout is frozen. Each run writes a new report, `data/runs/eval/<trial>/<run>.json`. `--holdout` evaluates the frozen holdout once per trial, last, and writes a promotion record only if every spec 8.6 criterion passes.
- `decide` always records a decision, WAIT until a verified promotion exists. The dashboard shows the same id. `--capital` overrides the saved capital for that run, and the override is recorded.
- Candidates B and C are refused (UNIMPLEMENTED). Horizons other than 20 and 60 for A are refused (UNREGISTERED_HORIZON).

All of these except `freeze-holdout` can also be requested from the dashboard's Controls tab; the scheduler runs them one at a time.

## F. Historical candles (Kite)

    .\.venv\Scripts\python.exe -m marketlab history --token 408065 --exchange NSE --symbol INFY --isin INE009A01021 --interval day --start 2025-01-01T00:00:00+05:30 --end 2026-01-01T00:00:00+05:30 --output data/raw/infy_daily_v1.csv
    .\.venv\Scripts\python.exe -m marketlab audit data/raw/infy_daily_v1.csv

Kite candles are **adjusted by Zerodha** for bonus, split, rights, spin-off and extraordinary dividends. The metadata records `series_kind: PROVIDER_ORIGINAL` and `adjustment_basis: PROVIDER_AS_OF_RETRIEVAL`.
- Do not apply the same corporate actions again.
- Do not use these prices as actual traded prices.
- Actual prices come from exchange bhavcopies.

    .\.venv\Scripts\python.exe -m marketlab backtest data/raw/infy_daily_v1.csv --fixed-cost 6000

That is a one-instrument diagnostic, not a strategy result. A BSE backtest requires the dataset metadata to record `bse_group` from listing data; there is no command-line override.

## G. News and other brokers

    .\.venv\Scripts\python.exe -m marketlab news --file data/examples/news.xml
    .\.venv\Scripts\python.exe -m marketlab import-trades path\to\your_normalized_trades.csv

Only official exchange feed hosts are accepted. Items are stored as unreviewed evidence; nothing turns a headline into a decision. Imported trades from another broker are observations, not a reconciled ledger.
