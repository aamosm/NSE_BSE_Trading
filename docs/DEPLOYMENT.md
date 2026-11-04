# Deployment: private server and phone app

Status 5 November 2026. **Prepared, not yet provisioned.** Nothing here has been run on a server yet. The units and scripts were syntax-checked, and the app, scheduler, login flow and SQLite restore were exercised on the Windows laptop.

What this gives you:
- the system runs without the laptop;
- you open a private app on your phone;
- once each trading morning you log in to Zerodha on Zerodha's own page.

The server can never place orders. The application has no order code.

## 1. What runs where

```
Phone (Tailscale app + browser/PWA)
   │  private HTTPS on your tailnet only (https://marketlab.<tailnet>.ts.net)
   ▼
Tailscale Serve on the server ──► 127.0.0.1:8765  marketlab-web   (app, Kite login callback)
                                   marketlab-scheduler            (collection, daily inputs, health, backups)
                                   marketlab-backup.timer         (encrypted copy to off-server storage)
Off-server: healthchecks.io (alerts if the server goes silent), ntfy (optional state alerts), Backblaze B2 (backups)
```

Login path:
1. App → **Log in to Kite** → kite.zerodha.com. You type your password and app code there.
2. Zerodha redirects the phone's browser to `https://marketlab.<tailnet>.ts.net/kite/callback`.
3. The server checks the path and the single-use state, exchanges the token, and checks the account is `KITE_USER_ID`.
4. Collection resumes within a minute.

The Zerodha redirect is a browser redirect, so Zerodha's servers never need to reach your server. The dashboard is never exposed to the internet.

Daily login stays manual. Kite tokens expire at 06:00 and can be invalidated earlier, and Zerodha requires manual login for this kind of app. Nothing automates the password, OTP, TOTP seed or browser cookies.

## 2. Costs (checked 5 Nov 2026; prices exclude taxes)

| Item | Purpose | Cost |
| --- | --- | --- |
| DigitalOcean Basic droplet, 1 vCPU / 2 GiB / 50 GiB SSD | always-on scheduler + app | **US$12/month**. A 1 GiB droplet is US$6 but has less headroom. Optional weekly droplet backups add 20% (US$2.40) |
| Tailscale Personal | private phone ↔ server network, HTTPS certificates | free (up to 6 users, unlimited devices) |
| healthchecks.io Hobbyist | independent "server went silent" alert | free (20 checks) |
| ntfy (ntfy.sh) | optional phone alerts on state changes | free public server |
| Backblaze B2 | encrypted off-server backups | first 10 GB free, then US$6.95/TB/month |
| Kite Connect | market and account data | ₹500/month (already paid) |

New recurring spend is **about US$12/month** (US$14.40 with droplet backups), plus GST charged by DigitalOcean. 2 GiB is a starting estimate, not a performance guarantee. Bulk replays and model fitting should run off the always-on server, or under the units' explicit CPU/memory limits.

## 3. One-time setup (owner, about 45 minutes)

Where you see `<...>`, type your own value. Never paste secrets into Git, chat or a model prompt.

### 3.1 SSH key on the laptop (PowerShell)

    ssh-keygen -t ed25519 -f $HOME\.ssh\marketlab -C marketlab
    Get-Content $HOME\.ssh\marketlab.pub    # copy this public key

### 3.2 Create the server

On digitalocean.com: **Create → Droplet**.
- Ubuntu 24.04 (LTS) x64.
- Region Bangalore (BLR1).
- Basic, Regular, US$12 (2 GiB).
- Authentication: **SSH key**. Paste the public key from 3.1.
- Hostname `marketlab`.

Note the droplet's public IP, then:

    ssh -i $HOME\.ssh\marketlab root@<droplet-ip>          # first login must work before the next step
    exit
    scp -i $HOME\.ssh\marketlab deploy\provision.sh root@<droplet-ip>:/root/
    ssh -i $HOME\.ssh\marketlab root@<droplet-ip> "sh /root/provision.sh"

`provision.sh` does the following:
- installs Python, git, age, rclone, sqlite3 and unattended upgrades;
- sets the clock to IST;
- creates the `marketlab` user and its private 0700 data directories;
- turns off SSH passwords, which it refuses to do unless a key is already installed;
- allows only SSH through the firewall.

### 3.3 Private network (Tailscale)

On the server:

    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up            # open the printed URL and sign in with your Tailscale account

In the Tailscale admin console:
1. DNS: enable **MagicDNS** and **HTTPS certificates**.
2. Machines: rename the server to `marketlab`.

On the phone, install the **Tailscale** app and sign in to the same account.

Optional, after `ssh root@marketlab` works over Tailscale: allow SSH only from the tailnet:

    ufw allow in on tailscale0 to any port 22
    ufw delete allow OpenSSH

### 3.4 Install a pinned release

Use a reviewed commit SHA, never a branch name:

    git clone https://github.com/aamosm/NSE_BSE_Trading.git /root/ml-bootstrap
    sh /root/ml-bootstrap/deploy/install_release.sh <commit-sha>

The script:
1. Exports that commit to `/opt/marketlab/releases/<sha>`.
2. Builds a virtual environment.
3. Runs the targeted boundary, login, app and scheduler tests.
4. Switches `/opt/marketlab/current` atomically.
5. Installs and starts the units, then checks `/health`.

If the GitHub repository is private, clone it with a read-only deploy key instead.

### 3.5 Secrets (typed on the server only)

    sudo -u marketlab sh -c 'umask 077; cp /opt/marketlab/current/deploy/env.example /var/lib/marketlab/private/.env; nano /var/lib/marketlab/private/.env'

Fill in:
- `KITE_API_KEY`, `KITE_API_SECRET` and `KITE_USER_ID`;
- `KITE_REDIRECT_URL=https://marketlab.<tailnet>.ts.net/kite/callback`;
- optionally `MARKETLAB_TAILNET_USER=<your Tailscale login email>`.

The program refuses any key it does not know, and any key whose name contains PASSWORD, PASSWD, PIN, TOTP or OTP. It cannot detect a password typed as the value of an allowed key, so never do that.

Edit `/etc/marketlab/marketlab.conf` (not secret) to set the watchlist (`SYMBOLS`). Then:

    systemctl restart marketlab-web marketlab-scheduler

### 3.6 HTTPS for the phone (Tailscale Serve, private only)

    tailscale serve --bg --https=443 http://127.0.0.1:8765
    tailscale serve status        # shows https://marketlab.<tailnet>.ts.net

**Do not use Tailscale Funnel.** It would make the app public.

### 3.7 Register the redirect with Zerodha

1. Open developers.kite.trade → your app.
2. Set the **Redirect URL** to exactly `https://marketlab.<tailnet>.ts.net/kite/callback`, the same string as `KITE_REDIRECT_URL`.

A Kite app has one redirect URL. After this change, the laptop's `marketlab auth` (which uses `http://127.0.0.1:8766/`) stops working. Log in from the phone app instead, or from a laptop browser connected to Tailscale.

### 3.8 Phone app

1. With Tailscale connected, open `https://marketlab.<tailnet>.ts.net` in Chrome.
2. Menu → **Install app** (or **Add to Home screen**).
3. Tap **Log in to Kite** and complete Zerodha's page. You should land on "Kite login complete".

Repeat the login on each trading day: the token from the previous day expires at 06:00. Log in before about 08:30 so pre-session collection runs.

The first successful phone login is the verification that the registered redirect works over the private connection. If you see "Login not accepted: LOGIN_WRONG_PATH", the registered URL and `KITE_REDIRECT_URL` differ.

### 3.9 Alerts that work even if the server dies

1. **healthchecks.io:** create a free account and a check with period 5 minutes and grace 15 minutes. Add your email or the ntfy integration. Put its ping URL in `.env` as `MARKETLAB_HEARTBEAT_URL`. The scheduler pings at most every 5 minutes, and adds `/fail` while DEGRADED. If the server or process dies, healthchecks.io notices the silence and alerts you. A process on a dead server cannot do that.
2. **Optional ntfy:**
   - Install the ntfy phone app and subscribe to a long random topic (e.g. 24 random letters).
   - Set `MARKETLAB_ALERT_URL=https://ntfy.sh/<that-topic>`.
   - Messages are fixed text with no account data: login needed, a job failing, recovered.
   - Anyone who guesses a public topic can read it, so the topic must be unguessable.
   - Delivery failures are shown in the app (`last_alert`).
3. Restart the scheduler after editing `.env`.

### 3.10 Encrypted off-server backups

1. On the laptop: `winget install FiloSottile.age`, then `age-keygen -o $HOME\marketlab-backup.key`. Keep this file **off the server**. Without it, backups cannot be decrypted.
2. Put the printed public key (`age1...`) in `/etc/marketlab/marketlab.conf` as `BACKUP_RECIPIENT`.
3. In Backblaze B2, create a private bucket and an application key limited to that bucket.
4. On the server: `sudo -u marketlab rclone config` → new remote `b2-marketlab` (type b2) with that key. Set `BACKUP_REMOTE=b2-marketlab:<bucket>/marketlab`.
5. Test that night after the scheduler's 23:30 snapshot, or after `sudo -u marketlab /opt/marketlab/current/.venv/bin/python -m marketlab --private-dir /var/lib/marketlab/private backup /var/lib/marketlab/backups/$(date +%F)/evidence.sqlite3`:

        systemctl start marketlab-backup.service && journalctl -u marketlab-backup -n 20

6. **Restore drill.** Download one archive to the laptop and run `deploy/restore_check.sh <archive> $HOME/marketlab-backup.key` in Git Bash or WSL. It decrypts, untars and runs SQLite `integrity_check`. Repeat monthly.

Backups contain the evidence and catalog databases, the security master and recent exchange files. They exclude `.env`, the Kite session and login states. Recreate `.env` by hand on a new server.

## 4. Operating

| Task | Command (server, as root) |
| --- | --- |
| Status | `systemctl status marketlab-scheduler marketlab-web`; the phone app's Health card |
| Logs | `journalctl -u marketlab-scheduler -n 100 --no-pager` (request lines are never logged) |
| Pause paper analysis | the app's **Pause analysis** button; collection continues |
| Update | `sh /opt/marketlab/current/deploy/install_release.sh <new-reviewed-sha>` |
| Roll back | `sh /opt/marketlab/current/deploy/rollback.sh` (or `rollback.sh <sha>`) |
| Stop everything | `systemctl stop marketlab-scheduler marketlab-web` |

Updates are never automatic. Deploy only a commit that has been reviewed.

## 5. Recovery

| Failure | What happens | What you do |
| --- | --- | --- |
| Kite token expired or invalidated | state AUTH_REQUIRED; exchange-file collection continues; ntfy alert if configured | log in from the phone app |
| An exchange source fails or changes format | per-source circuit breaker opens (15 min, doubling to 6 h); state DEGRADED; healthchecks gets `/fail` | check the app; a format change needs a code update |
| Process crash | systemd restarts it after 30 s; the lock prevents duplicates; collection is idempotent | nothing; check logs if it repeats |
| Server down | healthchecks.io alerts after 20 minutes of silence | reboot from the DigitalOcean console; if lost, rebuild with §3 and restore |
| Server lost | — | new droplet → §3.2–3.8 → decrypt the latest backup → copy `backups/<day>/evidence.sqlite3` to `/var/lib/marketlab/private/`, `catalog.sqlite3` and `raw/` to `/var/lib/marketlab/market/` (owner `marketlab`) |

No software can guarantee zero failures. The design aims for bounded behaviour, visible health and recoverability. The order-disabled architecture stops this application from trading; it does not remove market risk in holdings you buy yourself.

## 6. Until the server exists (laptop)

The laptop keeps working with the current registered redirect `http://127.0.0.1:8766/`:

    .\.venv\Scripts\python.exe -m marketlab auth                                      # daily login
    .\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY NSE:TCS             # scheduler (leave running)
    .\.venv\Scripts\python.exe -m marketlab dashboard                                 # app at http://127.0.0.1:8765

The phone cannot reach the laptop app until Tailscale is installed on both.
