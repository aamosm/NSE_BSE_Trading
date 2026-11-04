# Environment

Verified on 4 November 2026 by running each tool's `--version`.

| Item | Found |
| --- | --- |
| OS | Windows 11 Home Single Language 10.0.26200 |
| Python | 3.13.7 (`python` and `py`; `python3` is not on PATH) |
| pip | 25.2 |
| Node / npm | 24.16.0 / 11.13.0 |
| Git | 2.51.0.windows.1 |
| Docker | Client 29.7.2 (daemon not exercised) |
| Java | OpenJDK 17.0.20.1 (relevant later for the Android build) |
| PostgreSQL client (`psql`) | Not installed |
| uv | Not installed (not needed) |
| `ANTHROPIC_API_KEY` | Not set (existence checked, value not printed), so Claude Code is using subscription billing |
| Project Git repository | Initialised 4 Nov 2026 (branch `main`, local only, no remote) |
| Reference projects | 20 read-only shallow clones in `C:\Users\d_hru\try\tradebot\reference_bots\` (outside this repository; never installed or run) |

## Setup (already done once in this folder)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.lock
```

## Run

```powershell
.venv\Scripts\python -m pytest                 # all tests
$env:PYTHONPATH = "src"; .venv\Scripts\python -m marketlab.rules.demo    # rule decisions on synthetic orders
$env:PYTHONPATH = "src"; .venv\Scripts\python -m marketlab.ledger.demo   # full cash + MTF replay: decisions, ledger, metrics
```

The runtime package has no third-party dependencies. Times use a fixed +05:30 offset (India has no DST), so no tz database is needed on Windows.

## Missing for later phases

- **PostgreSQL** (Phase 1 ledger). Use Docker (`docker run postgres:<pinned>`) or a local install. Decide in ARCHITECTURE_DECISIONS.md.
- **Android SDK** (Phase 9).
- **No broker credentials, API keys or paid services** are needed or configured for Phase 0/1.
