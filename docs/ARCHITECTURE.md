# Architecture and extension boundaries

The runtime is deliberately small enough to audit. Most of the complexity belongs in data correctness, model validation and risk-aware allocation, not a large service fleet.

    src/marketlab/kite.py             fixed-host, read-only transport (GET allowlist + token exchange)
    src/marketlab/login.py            official Kite login: state, callback checks, account check, session
    src/marketlab/store.py            append-only evidence: first-known time, every receipt, batches
    src/marketlab/account.py          actual-account view from one completed batch; unknowns explicit
    src/marketlab/sources.py          official exchange source register and polite collector
    src/marketlab/master.py           security master and daily InstrumentSnapshot builder with provenance
    src/marketlab/corporate_actions.py provider / exchange / derived price series; action effects
    src/marketlab/service.py          calendar-driven scheduler, health states, breakers, alerts
    src/marketlab/webapp.py           private phone app server and login callback (loopback only)
    src/marketlab/webassets.py        PWA shell, worker, manifest, icons (no third-party code)
    src/marketlab/news.py             bounded RSS/Atom evidence ingestion
    src/marketlab/cli.py              commands
    src/marketlab/audit.py            dataset provenance/missingness checks
    src/marketlab/costs.py            single-order cost estimate over rules.charges
    src/marketlab/backtest.py         diagnostic controls and chronological fold ranges
    src/marketlab/experiments.py      started/completed/failed research records
    src/marketlab/research.py         forecast contract, one-entry paper sizing and wording
    src/marketlab/rules/              cash-equity exchange/broker rules engine (calendars incl. special sessions,
                                      sessions, ticks, bands, T2T series, surveillance, Kite order constraints,
                                      cited fee schedule with day-level STT); every paper proposal passes it
    src/marketlab/metrics/            returns, risk, PSR/DSR/PBO selection statistics, trade and cost metrics
    deploy/                           systemd units, provisioning, pinned release install/rollback, backups

Processes on the server: `marketlab-scheduler` (collection and daily inputs) and `marketlab-web` (phone app), both as user `marketlab`, both bound to loopback or outbound only. The phone reaches the app through Tailscale Serve. Bulk exchange files (`market/raw`) and their catalog are kept apart from private account evidence (`private/evidence.sqlite3`).

## What owns each decision

| Decision | Owner |
| --- | --- |
| Whether a source fact is well supported | Data validation and evidence lineage |
| Expected outcomes over a horizon | Fable's future fitted/calibrated model |
| Whether exposure is affordable and allowed | Deterministic cash/risk policy |
| What quantity to propose across the account | Future serialized portfolio coordinator |
| Whether to make a real broker order | No component in this package |
| What the user is told | Deterministic templates using recorded fields |

The collector and research commands currently share a package, but are distinct processes. For future hosted model workers, run research under a separate OS user without access to kite_session.json or raw account identifiers. A service boundary or container can enforce that separation once the worker exists.

## Why the baselines are simple

A baseline has to be easy to falsify and reproduce. If a complex text/analogue model cannot improve on a simple price control after costs and proper validation, its complexity is not useful. The baseline is an instrument for evaluating Fable's work, not the promised final forecasting algorithm.

## Before a portfolio loop exists

The single-entry sizing function takes existing stock/sector/sleeve exposure and available cash as inputs. Calling it twice with the same stale balances can over-allocate. No automatic loop calls it today. The coordinator must atomically reserve cash, aggregate by ISIN, account for all existing/manual holdings and reevaluate the remaining budget after each plan. Tests must include two simultaneous proposals and a restart before a reservation is released.

## Why the historical simulator remains exploratory

The current simulator consumes one instrument's OHLCV and has no complete market-specific corporate-action/calendar/eligibility engine. These limitations are embedded in every result. It is useful for verifying data plumbing, delayed signal execution, basic cost economics, cash constraints and model-interface integration.

It must be extended or replaced before claiming realistic portfolio profitability. The archived accounting code may supply ideas, but carries the review's known defects and must not be imported to make the active system appear more complete.
