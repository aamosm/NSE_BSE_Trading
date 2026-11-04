# Kite and server setup

This guide connects DATA only. No order endpoint exists in the application. Account authentication and a real cloud deployment have not been performed by the author of this reset.

## A. First run locally

Follow README_FIRST.md to install, test and run the synthetic demo. Do this before paying for a server. Keep the project in your own Windows account folder, not a shared/cloud-public directory.

The active package has no third-party runtime dependency. The pinned requirements-dev.lock is for tests. Python 3.12 or newer is required.

## B. Create the Kite app

1. Open https://developers.kite.trade/ yourself and use the official registration flow.
2. Choose the paid market/historical-data plan if you need quote/history access. The published price checked on 4 November 2026 is ₹500/month per API key. Personal/free does not include those data services [S01].
3. Use your own Kite account with the app. Follow the console's current app/account fields.
4. Set the redirect URL to http://127.0.0.1:8766/callback for this manual token-copy workflow. The program does not run a callback server; the browser may show a connection error after successful Kite login. The redirect URL in its address bar contains the short-lived request_token.
5. Keep the API key and secret privately. Do not commit them, paste them into Claude/Fable/ChatGPT, put them in command arguments, or screenshot the resulting token URL.

Run in PowerShell from the project folder:

    .\.venv\Scripts\python.exe -m marketlab auth

The program asks for the key/secret using hidden input, opens the official login page, and then asks for the request token or whole redirected URL using hidden input. Complete password/OTP entry yourself in Kite. Paste the redirect immediately; request tokens expire within minutes. It exchanges that token through the documented API, saves only the resulting key/access-token/expiry locally, and does not store your API secret.

If the developer console rejects the local redirect URL or the login page behaves differently, stop and use its current supported redirect configuration; do not bypass authentication. The provider flow must be verified on your account.

The session file is data/private/kite_session.json. Unix permissions are restricted. On Windows, store it under your private user directory and use the file's Security properties to restrict other local users; chmod is not a substitute for auditing Windows ACLs.

## C. Test read-only collection

    .\.venv\Scripts\python.exe -m marketlab collect --instruments --symbols NSE:INFY
    .\.venv\Scripts\python.exe -m marketlab dashboard

The example symbol is for data testing, not a recommendation. Review the private NSE/BSE master files to choose the current symbol and token. Quote collection and historical access require the paid data entitlement.

Collection records holdings, positions, today's trades and funds. This is not complete historical account reconciliation. Broker actions from Kite on the same account can appear in these reads; another broker/app requires an export and normalized import:

    .\.venv\Scripts\python.exe -m marketlab import-trades path\to\your_normalized_trades.csv

See data/examples/external_trades.csv for the columns. Real files stay out of Git. Imported observations do not automatically produce a reconciled cross-broker cash/holdings ledger.

## D. Download a bounded historical dataset

Find the current token in data/private/instruments_NSE.json or instruments_BSE.json. Obtain the correct ISIN from an official security master or reconciled holding; the Kite instrument dump itself does not supply it.

Substitute your verified values into this ONE-LINE PowerShell command:

    .\.venv\Scripts\python.exe -m marketlab history --token YOUR_NUMERIC_TOKEN --exchange NSE --symbol YOUR_SYMBOL --isin YOUR_ISIN --interval day --start 2025-01-01T00:00:00+05:30 --end 2026-01-01T00:00:00+05:30 --output data/raw/your_symbol_daily_v1.csv

The adapter verifies that token/symbol/exchange match one current EQ listing. ISIN is still an explicitly user-supplied mapping and must be reviewed. It downloads in bounded chunks and writes a metadata file listing unverified historical factors. It excludes incomplete candles. Daily bars are conservatively marked available at 23:59:59 IST, for next-session research.

For intraday experiments choose 5minute or another documented interval and shorter ranges. The collection is REST-based; there is no WebSocket tick recorder yet.

    .\.venv\Scripts\python.exe -m marketlab audit data/raw/your_symbol_daily_v1.csv
    .\.venv\Scripts\python.exe -m marketlab backtest data/raw/your_symbol_daily_v1.csv --fixed-cost 6000

The ₹6,000 example represents twelve months of the published Kite fee only; use the actual operating cost for the dataset period, including hosting and optional APIs. Cash/buy-hold benchmarks assume no recurring research service. The trend candidate bears the supplied service cost.

These are EXPLORATORY baselines. Metadata flags, settlement approximations and missing corporate-action handling prevent strategy certification. Backtest reports get unique run folders; failed runs remain in the evidence database.

## E. News

For a saved XML file:

    .\.venv\Scripts\python.exe -m marketlab news --file data/examples/news.xml

That supplied file is synthetic. For real feeds, use the official NSE RSS directory in SOURCE_PACK.md, copy the feed URL, and run:

    .\.venv\Scripts\python.exe -m marketlab news --url YOUR_OFFICIAL_HTTPS_FEED_URL

Only listed official exchange hosts are accepted. If the website blocks access, use its supported browser export or licensed access; no cookie/anti-bot bypass is included. News remains unreviewed evidence. Feed polling is not part of the current watch command; add a bounded scheduler after verifying the chosen feed.

## F. Daily login is part of the workload

Kite's access token normally expires at 06:00 the following day and may be invalidated earlier [S24]. Run auth again each collection day. The collector detects expiry and records a failed/paused status; it does not store OTP seeds or automate login.

A paid API does not make this system maintenance-free. This daily step matters to the user's part-time requirement.

## G. Put the modified code on GitHub before cloning it to a server

The delivered ZIP has not changed your GitHub main branch. Cloning main alone would retrieve the OLD project.

The ZIP includes UPGRADE.patch against the reviewed upstream commit. Ask Claude to check a clean working tree and apply it on a new branch. Example commands in a FRESH clone:

    git clone https://github.com/aamosm/NSE_BSE_Trading.git NSE_BSE_Trading_reset
    cd NSE_BSE_Trading_reset
    git switch -c cash-research-reset 19d12dcac7415b17d3a5192035517ad285f9b389
    git status --short
    git apply --check C:/path/to/extracted/UPGRADE.patch
    git apply C:/path/to/extracted/UPGRADE.patch

If the check fails, stop and have Claude reconcile the changes; do not force the patch or discard existing work.
Run the tests and review git diff. Then, when satisfied:

    git add .
    git commit -m "Reset to cash-only research and read-only Kite data"
    git push -u origin cash-research-reset

Keep the ZIP's full source as an independent copy. UPGRADE.patch excludes itself and generated runtime/private files.

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

Authenticate over SSH using hidden input:

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
