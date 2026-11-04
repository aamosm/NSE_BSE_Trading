# Start here

**Research and data collection only. This application cannot place, modify or cancel broker orders.**

The old project was a rules/accounting simulator, not a finished stock-selection system. This is a scoped cash-only reset from upstream commit 19d12dcac7415b17d3a5192035517ad285f9b389.

## What works now

| Capability | Implemented behavior |
| --- | --- |
| Kite REST adapter | Narrow read allowlist; login token exchange is the only POST |
| Data collection | Holdings, positions, today's trades, funds, quotes and daily instrument-master snapshots |
| Historical candles | Bounded requests, token/symbol/exchange verification, CSV export and explicit metadata gaps |
| News | Official-host RSS download or saved XML import; timestamped unreviewed evidence |
| Audit | Append-only SQLite evidence, content deduplication, revisions, quota, consistent backup |
| External trades | Normalized CSV import as evidence; not yet a reconciled multi-broker ledger |
| Backtests | Cash/buy-hold/trend comparisons and an intraday-reversal diagnostic; fees, slippage, cash constraints and decision logs |
| Forecast interface | Distributions, calibration/evidence identifiers, expiry, sample count and validation gate |
| Paper sizing | Whole shares, cash reserve, stock/sector/sleeve/risk/liquidity/cost constraints |
| Status page | Mobile-friendly, loopback-only, deterministic wording, no order controls |
| Exchange rules | Cash-only engine with sources: holiday, settlement and Budget-Sunday calendars; pre-open/CAS sessions; ticks; bands; T2T; surveillance stages; Kite order limits. Paper proposals abstain without a dated snapshot |
| Metrics | Time-weighted return, XIRR, drawdowns, Sharpe (risk-free rate required), Sortino, PSR, DSR, PBO with midrank ties, trade and cost statistics |
| Read-only summary | `python -m marketlab summary` prints the latest collected holdings, funds, positions and trades |

Not implemented: production forecasts, full portfolio optimization/rebalancing, autonomous paper-trading loop, exchange-grade fill simulation, full corporate-action/settlement engine, news-to-signal extraction, historical point-in-time universe, WebSocket tick recorder, or live orders.

## Run the offline demonstration on Windows

Extract into a NEW folder; do not overlay it blindly onto the old source tree.
Open a VS Code terminal in this folder:

    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
    .\.venv\Scripts\python.exe -m pytest
    .\.venv\Scripts\python.exe -m marketlab demo
    .\.venv\Scripts\python.exe -m marketlab dashboard

Open http://127.0.0.1:8765. Compatible Python 3.13 is also acceptable; substitute its launcher selector. The delivered tests were run on Linux Python 3.12.14; Windows setup commands still need local execution.

## Do these next, in order

1. Give Claude this whole folder and prompts/01_CLAUDE_ENGINEERING.txt. It should audit and finish the specified engineering gaps before quantitative work.
2. Set up Kite read-only collection with docs/KITE_AND_SERVER_SETUP.md. Never paste keys into an AI conversation.
3. Give Fable the updated repo, docs/RESEARCH_BRIEF.md, docs/FABLE_MATH_SPEC.md, docs/SOURCE_PACK.md and prompts/02_FABLE_QUANT.txt.
4. After Fable returns code/model specifications, run prompts/03_VALIDATION.txt with a separate testing model, then prompts/04_INDEPENDENT_REVIEW.txt.
5. Do not turn a passing test suite into permission to trade. This package has no live switch.

docs/reviews/PHASE_0_1_REVIEW.md preserves the previous independent review.
docs/RESET_REVIEW.md explains which findings were removed from active scope and which controls replaced them.
archive/phase_0_1 contains every original tracked upstream file, including the old MTF implementation and planned registries. It is not installed or included in active test discovery.
