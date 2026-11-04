# Kite and server setup

This guide connects DATA only. The application has no order, conversion, GTT or fund-transfer endpoint. Verified on 4 Nov 2026 on the user's Windows laptop, which is the "server" until the project is finished.

## A. Install (Windows, PowerShell, in the project folder)

    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
    .\.venv\Scripts\python.exe -m pytest

The runtime uses only the Python standard library. The lock file pins the test tools.

## B. Kite developer app

1. Create the app yourself at https://developers.kite.trade/. Quotes and historical candles need the paid Kite Connect plan (₹500/month per API key, checked 4 Nov 2026) [S01]. This account's app has that entitlement: quotes and history were verified.
2. Set the app's redirect URL to `http://127.0.0.1:8766/`. Any path on that port works.
3. Create `data/private/.env`. Both `data/private/` and `.env*` are git-ignored.

       KITE_API_KEY=your_api_key
       KITE_API_SECRET=your_api_secret
       KITE_USER_ID=your_client_id

   Never add your Zerodha password, PIN or TOTP seed. The program refuses to start if the file contains such a key. Restrict the folder to your Windows user (Properties → Security), or run:

       icacls data\private /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"
       Get-ChildItem -Force data\private | ForEach-Object { icacls $_.FullName /reset }

## C. Daily login

    .\.venv\Scripts\python.exe -m marketlab auth

The program reads the key and secret from `.env`, opens Zerodha's official login page, and listens on 127.0.0.1:8766 for the redirect. You type your password and app code into Zerodha's page; the program never sees them. It exchanges the short-lived request token, checks that the account is `KITE_USER_ID`, and saves only the access token in `data/private/kite_session.json`.

If the port is busy or nothing arrives within `--wait` seconds (default 300), it asks you to paste the redirected URL instead, in a hidden prompt.

Tokens expire at 06:00 the next day and can be invalidated earlier [S24], so log in once each collection day. Expired sessions stop collection with an explicit message. Logging in is never automated.

## D. Read-only collection and summary

    .\.venv\Scripts\python.exe -m marketlab collect --instruments --symbols NSE:INFY
    .\.venv\Scripts\python.exe -m marketlab summary
    .\.venv\Scripts\python.exe -m marketlab dashboard

Collection stores holdings, positions, today's trades, funds, optional quotes and the NSE/BSE instrument dumps as append-only evidence in `data/private/evidence.sqlite3`. If the Kite plan refuses an endpoint, it is recorded as unavailable (`COLLECTED_PARTIAL`) and the other reads continue.

`summary` prints the latest snapshot in the terminal only. The dashboard (127.0.0.1:8765) shows sanitized status, never holdings or identifiers.

Activity from other Kite apps on the same account appears in these reads. Another broker requires a normalized CSV import:

    .\.venv\Scripts\python.exe -m marketlab import-trades path\to\your_normalized_trades.csv

See `data/examples/external_trades.csv`. Imported rows are observations, not a reconciled ledger.

## E. Historical candles

Find the token in `data/private/instruments_NSE.json`. Take the ISIN from the exchange master or a reconciled holding; the Kite dump does not supply it.

    .\.venv\Scripts\python.exe -m marketlab history --token 408065 --exchange NSE --symbol INFY --isin INE009A01021 --interval day --start 2025-01-01T00:00:00+05:30 --end 2026-01-01T00:00:00+05:30 --output data/raw/infy_daily_v1.csv
    .\.venv\Scripts\python.exe -m marketlab audit data/raw/infy_daily_v1.csv

The command checks that the token, symbol and exchange identify one current EQ listing. It downloads in bounded chunks, excludes incomplete candles and writes a metadata file listing unverified factors: corporate actions, historical universe, historical status and historical fees.

Daily bars are marked available at 23:59:59 IST, for next-session research. Whether Kite candles are corporate-action adjusted is **not yet verified** (ROADMAP §4).

    .\.venv\Scripts\python.exe -m marketlab backtest data/raw/infy_daily_v1.csv --fixed-cost 6000

That is a one-instrument diagnostic. The ₹6,000 is twelve months of the Kite fee charged against the trend candidate. It is not a strategy result.

## F. News

    .\.venv\Scripts\python.exe -m marketlab news --file data/examples/news.xml
    .\.venv\Scripts\python.exe -m marketlab news --url YOUR_OFFICIAL_HTTPS_FEED_URL

Only listed official exchange hosts are accepted, with no anti-bot bypass. Items are stored as unreviewed evidence; there is no news-to-signal extraction yet.

## G. GitHub and a future server

The work is on the local branch `cash-research-reset`. GitHub `main` still holds the old phase-1 commit. When you are ready, push the branch (`git push -u origin cash-research-reset`) and merge it after review. A server should clone the reviewed branch. Recreate `data/private/.env` on the server by hand; never commit it.

## H. Optional Ubuntu server

Recommended starting scope: Ubuntu 24.04 LTS, one vCPU, 1–2 GiB RAM, local SSD, SSH-key access. The collector/status page are light; do heavy training elsewhere. DigitalOcean's current 1 GiB example is US$6/month before extras [S21]. Existing hardware is cheaper. No server has been purchased or provisioned for you.

On the server, as an administrator:

    sudo apt update
    sudo apt install -y python3 python3-venv git curl
    sudo useradd --system --create-home --home-dir /var/lib/marketlab --shell /usr/sbin/nologin marketlab
    sudo git clone --branch cash-research-reset https://github.com/aamosm/NSE_BSE_Trading.git /opt/marketlab
    sudo python3 -m venv /opt/marketlab/.venv
    sudo /opt/marketlab/.venv/bin/python -m pip install /opt/marketlab
    sudo install -d -o marketlab -g marketlab -m 700 /var/lib/marketlab

The branch must exist first. If your repo is private, set up read-only Git access through your provider's supported flow; never embed a personal token in the clone URL or service unit.

First create /var/lib/marketlab/.env (owner marketlab, mode 600) with the same three KITE_ keys as on the laptop. Then authenticate over SSH. With --no-browser the redirect cannot reach the server, so you paste the redirected URL into the hidden prompt:

    sudo -u marketlab /opt/marketlab/.venv/bin/python -m marketlab --private-dir /var/lib/marketlab auth --no-browser

On your own computer, use the official login URL described in Kite's documentation with your public API key:

    https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_PUBLIC_API_KEY

Complete login yourself and paste the resulting request token into the hidden SSH prompt. Do not paste it into the shell command line or an AI chat.

First collection:

    sudo -u marketlab /opt/marketlab/.venv/bin/python -m marketlab --private-dir /var/lib/marketlab collect --instruments --symbols NSE:INFY

Install and start the two services:

    sudo cp /opt/marketlab/deploy/marketlab-collector.service /etc/systemd/system/
    sudo cp /opt/marketlab/deploy/marketlab-dashboard.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now marketlab-collector marketlab-dashboard
    sudo systemctl status marketlab-collector marketlab-dashboard

The supplied collector service reads account snapshots; add a small --symbols list to its ExecStart if you want quotes continuously. Keep --interval at 300 initially. After editing a unit, run daemon-reload and restart that service.

The units cap CPU/memory and restrict filesystem writes. The dashboard listens only on 127.0.0.1. No public 8765 firewall opening is needed.

## I. Computer and phone access

From your laptop:

    ssh -L 8765:127.0.0.1:8765 YOUR_SERVER_USER@YOUR_SERVER_IP

Open http://127.0.0.1:8765 while that tunnel runs.

For a phone, install Tailscale on the server and phone using the official instructions:
https://tailscale.com/docs/install/linux

The official Linux installer can be downloaded and reviewed before running:

    curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
    less /tmp/tailscale-install.sh
    sudo sh /tmp/tailscale-install.sh
    sudo tailscale up
    sudo tailscale serve --bg 8765

Follow Tailscale's displayed authorization steps and permit only your intended devices/account. Open its private HTTPS URL on your phone while connected to your tailnet. Use Serve; do not enable public Funnel. This is a responsive status page, not a native Android application.

## J. Operations, backups and updates

Inspect sanitized service logs:

    sudo journalctl -u marketlab-collector -n 50 --no-pager
    sudo journalctl -u marketlab-dashboard -n 50 --no-pager

Stop collection:

    sudo systemctl stop marketlab-collector

Consistent backup:

    sudo -u marketlab /opt/marketlab/.venv/bin/python -m marketlab --private-dir /var/lib/marketlab backup /var/lib/marketlab/backups/evidence-YYYY-MM-DD.sqlite3

Copy backups securely off the server and test restoring into a separate folder. They contain private broker data. The quota fails visibly at roughly 256 MiB; it does not delete records automatically.

After a reviewed update is pushed:

    sudo systemctl stop marketlab-collector marketlab-dashboard
    sudo git -C /opt/marketlab pull --ff-only
    sudo /opt/marketlab/.venv/bin/python -m pip install --upgrade /opt/marketlab
    sudo systemctl start marketlab-collector marketlab-dashboard

Do not run research jobs as root or in the credential-bearing collector process. Before running expensive history/model jobs, set request/time/disk budgets.

Static IP is not needed for the read-only endpoints used here. It is a separate requirement for any future API-order system [S23], which this package deliberately does not contain.
