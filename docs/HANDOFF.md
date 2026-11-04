# Handoff

Updated 5 November 2026 by Claude (implementation owner).
- **Milestone:** 1 of the consolidated handoff: foundation corrections, data collection, deployment preparation, phone dashboard and login.
- **Branch:** `cash-research-reset`, on top of `3513d33` (GPT's last review). Pushing to GitHub is the owner's call.
- **Privacy:** no account identifiers, tokens or balances appear in this file.

## Scope

- Cash-only NSE/BSE research and paper decisions. Read-only Kite; simulated execution only.
- Private server plus phone PWA over Tailscale.
- No MTF, borrowing, shorting, derivatives, orders or live switch.

## Commits

| Commit | What |
| --- | --- |
| `2d53906` | Snapshot chronology: latest receipt + completed batch decide the current state; per-section states; unknown is not zero; trade book attributed to a session only after it opens |
| `e4544e1` | Login: single-use hashed expiring state, exact callback path, mandatory account check, enumerated error labels, 90 s read deadline, env allowlist, fix of the 00:00–06:00 expiry bug |
| `1472281` | Costs and decision time: day-level STT rounded to the rupee, stamp UNRESOLVED, DP from the funds statement, submission revalidation, BSE fee group from listing data |
| `e605514` | Muhurat 8 Nov 2026 session and settlement tables (NSE/CMTR/76941, NCL/CMPT/77037) |
| `f431de9` | Corporate actions: provider / exchange / derived price series, action effects, provider reconciliation |
| `0f8c972` | Public data: source register, polite collector, security master, daily `InstrumentSnapshot` builder |
| `bc4aeda` | Scheduler `run`: calendar-driven jobs, health states, breakers, pause, heartbeat and alerts |
| `b0f478c` | Phone app: private PWA and the official Kite login callback; actual and simulated accounts separate |
| `88dd10b` | Deployment kit: systemd units, provisioning, pinned release/rollback, encrypted backups, `DEPLOYMENT.md` |
| `8a06ae7` | Web unit: writable data directory (SQLite WAL readers need it) |
| `d7383b4` | Sources: NSE index closes and clearing holidays; `verify-calendar` |
| `d939cb0` | Login catcher threaded (idle browser connections could delay the redirect) |
| docs commit | This handoff, `DATA_READINESS.md`, `SOURCE_STATUS.md`, `FABLE_HANDOFF.md`; scope updates to AGENTS, CLAUDE, README, ROADMAP, GPT_SUMMARY, RULES_REGISTER, RESET_REVIEW, ARCHITECTURE, setup guide and Fable prompts |

## Verified on this laptop (Windows 11, Python 3.13.7)

**Targeted tests, run with each change:**
- `test_snapshot_chronology`, `test_login_flow`, `test_kite_login`;
- `test_costs_and_decision_time`, `test_research`, `test_boundaries`, `test_charges_broker`, `test_properties_provenance`, `test_metrics`;
- `test_muhurat_2026`, `test_calendar_sessions`, `test_engine`;
- `test_corporate_actions`, `test_integration`;
- `test_public_data`, `test_service`, `test_webapp`.

All passed in their final runs. 148 tests are new (8 files); 435 are collected in total. The unchanged suite was not re-run just for a count. One timing-dependent failure was found and fixed (`d939cb0`).

**Real data (read-only):**
- `fetch-public` stored 15 official sources (4 Nov dated files, 5 Nov vintages, 30 Oct bhavcopy).
- Security master for 5 Nov: 2,627 NSE / 5,044 BSE listings, 2,434 ISINs on both, 0 ISIN conflicts.
- Snapshots built for INFY, 21STCENMGM, BLUECHIP and MILTON, including two real series changes. Through the engine, the GSM-2 stock's fresh buy was blocked and the ESM-1 BE stock was accepted for delivery with a warning.
- `verify-calendar 2026`: trading holidays (16) and settlement holidays (20) AGREE with NSE's APIs.
- Archive depth spot-checked: bhavcopy to 2016, sec_list to 2022, REG1_IND to Jan 2025, index closes to 2020.
- One Kite collection **batch** completed. Holdings, positions and funds OK; the 01:xx trade book is labelled SESSION_UNKNOWN.
- `run --once`: RUNNING; the public_eod job OK.
- App on loopback: status, shell, manifest, icons and worker served.
- Backup restore: SQLite backup → tar → restore → `integrity_check` ok for the evidence and catalog databases.

**Not run:**
- any server step;
- phone login through Tailscale;
- `age` encryption (not installed here);
- contract-note and funds-statement reconciliation;
- corporate-action reconciliation (no official history yet);
- any order action (none exists).

## Remaining blockers

1. **Server not provisioned.** Everything for it is prepared (`DEPLOYMENT.md`). The phone login is the end-to-end check of the redirect.
2. **No historical backfill**, so no horizon is testable yet (`DATA_READINESS.md`). The old-format bhavcopy parser is not written.
3. **No official corporate-action history.** Kite history is provider-adjusted; base prices on ex-dates are set to unknown.
4. **Cost basis unreconciled:** STT aggregation (ASSUMPTION), stamp allocation (UNRESOLVED), DP amount per account.
5. **Rule-input assumptions:** REG1_IND `Status` → suspended and `ICA` → call auction; sec_list/REG1_IND describe the next session (observed, not documented).
6. **Unloaded:**
   - BSE calendar, bands and surveillance;
   - 2027 NSE calendar;
   - historical F&O membership;
   - broker MIS list;
   - Zerodha's Muhurat MIS square-off time.
7. **Not built:** model, allocator, simulated cash ledger, replay harness, financial filings, earnings-event path.
8. **Exchange website terms of use** not reviewed.
9. **Legacy account evidence.** Collections before 5 Nov have no batch, so the account view starts from the 5 Nov batch.

## One-time actions for the owner

1. **Change the Zerodha password.** It was typed into an earlier chat. Optionally regenerate the Kite API secret, then update `data/private/.env`.
2. **Push the branch** when you want GPT to review it: `git push origin cash-research-reset`.
3. **Rent the server and follow `docs/DEPLOYMENT.md` §3 in order:**
   - SSH key, then a DigitalOcean Ubuntu 24.04 2 GiB droplet in BLR1, then `provision.sh`;
   - Tailscale on the server and the phone (enable MagicDNS + HTTPS);
   - `install_release.sh <reviewed SHA>`;
   - type `.env` on the server;
   - `tailscale serve --bg --https=443 http://127.0.0.1:8765`.
4. **Change the Kite app's redirect URL** to `https://marketlab.<tailnet>.ts.net/kite/callback` and set the same `KITE_REDIRECT_URL`. After this, the laptop's `marketlab auth` no longer works; log in from the app.
5. **Install the app** on the phone (Chrome → Install app) and complete one login. This verifies the redirect over the private connection.
6. **Alerts:** a healthchecks.io free check (5 min period, 15 min grace) → `MARKETLAB_HEARTBEAT_URL`. Optional: an ntfy topic → `MARKETLAB_ALERT_URL`.
7. **Backups:**
   - `age-keygen` on the laptop, keeping the key off the server;
   - a B2 bucket and a key limited to it;
   - `rclone config` as user `marketlab`;
   - one restore drill with `restore_check.sh`.
8. **Optional:** reconcile one contract note and the matching funds statement locally against `rules.charges.day_charges`. Report only matches and mismatches; never commit the documents.
9. **Daily:** log in from the phone each trading morning, before about 08:30.

## Commands (laptop)

```powershell
.\.venv\Scripts\python.exe -m marketlab auth
.\.venv\Scripts\python.exe -m marketlab run --symbols NSE:INFY NSE:TCS
.\.venv\Scripts\python.exe -m marketlab dashboard
.\.venv\Scripts\python.exe -m marketlab fetch-public --date 2026-11-04
.\.venv\Scripts\python.exe -m marketlab snapshot --date 2026-11-05 --symbol INFY
.\.venv\Scripts\python.exe -m marketlab verify-calendar --year 2026
```

## Next task

`docs/ROADMAP.md` §2, step 2: the historical backfill, then corporate actions. No Fable session until `DATA_READINESS.md` is refreshed after the backfill.
