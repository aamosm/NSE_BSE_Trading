# Architecture and extension boundaries

The runtime is deliberately small enough to audit. Most of the complexity belongs in data correctness, model validation and risk-aware allocation, not a large service fleet.

    src/marketlab/kite.py         fixed-host, read-only transport
    src/marketlab/store.py        original observations, receipts, as-of queries, backup
    src/marketlab/news.py         bounded RSS/Atom evidence ingestion
    src/marketlab/cli.py          login, collection, exports and offline commands
    src/marketlab/audit.py        dataset provenance/missingness checks
    src/marketlab/costs.py        explicit cash-equity cost estimates
    src/marketlab/backtest.py     diagnostic controls and chronological fold ranges
    src/marketlab/experiments.py  started/completed/failed research records
    src/marketlab/research.py     forecast contract, one-entry paper sizing and wording
    src/marketlab/dashboard.py    local read-only status display

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
