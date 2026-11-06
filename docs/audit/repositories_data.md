<!-- Copied 2026-11-07 from tradebot-india-audit/research_notes/Indian trading systems audit/repositories_data.md (the external audit's deliverable, unedited). Relative links point into that audit folder. -->

# Indian equity repositories and public data

## Which repositories are practical for this project?

### Takeaway

Keep the existing direct exchange-file pipeline and narrow Kite adapter. Add independent calculation comparisons and selected source-specific research adapters where they fill measured gaps; replacing the working data layer with a large scraper or trading platform is not justified. This is a 16-repository comparative inspection of metadata, pinned documentation/root trees and selected source code, not a certification of every repository or execution of their tests. Metadata was retrieved on 6 November 2026; exact commit hashes are in [repository_manifest.json](../../evidence/repos/repository_manifest.json).

### Cited Findings

The date below is the latest commit returned for the **default branch**, which is more relevant than a repository's last star/metadata update. Neither a recent commit nor stars proves correctness. Source links in each row identify the inspected projects; pinned source URLs for important findings follow the table.

| Repository | Default branch commit date | Observed licence | Assessment for this cash-equity paper research system |
|---|---|---|---|
| [maanavshah/stock-market-india](https://github.com/maanavshah/stock-market-india) | 2021-12-14 | MIT | Do not adopt as primary feed. Small Node scraper/API example, old NSE endpoint family, no meaningful package test command. |
| [aeron7/nsepython](https://github.com/aeron7/nsepython) | 2026-10-07 | GPL-3.0 | Useful educational catalogue of NSE functions, beta and option calculations. Current transport and one beta implementation need scrutiny; not an authoritative feed or validated strategy. |
| [aeron7/nsepythonserver](https://github.com/aeron7/nsepythonserver) | 2026-10-07 | GPL-3.0 | Server variant of the same family; not an independent confirmation of NSEPython results. |
| [jugaad-py/jugaad-data](https://github.com/jugaad-py/jugaad-data) | 2026-10-22 | Custom YOLO file declares public domain | Worth examining for cached download patterns, index historical data and total-return-index access. Needs endpoint and licence review before integration. |
| [BennyThadikaran/NseIndiaApi](https://github.com/BennyThadikaran/NseIndiaApi) | 2026-10-30 | GPL-3.0 | Strong candidate to study for corporate filings/history breadth and structured transport; current v5 breaking changes and cookie/retry behavior need explicit compatibility review. |
| [zerodha/pykiteconnect](https://github.com/zerodha/pykiteconnect) | 2026-09-15 | MIT | Best official reference client for the broker already chosen. Retain a read-only facade; do not expose the SDK's order methods to models. |
| [upstox/upstox-python](https://github.com/upstox/upstox-python) | 2026-09-07 | MIT | Official alternative broker SDK; docs include sandbox and market stream functions. Evaluate only against a concrete missing-data need, not to increase API count. |
| [dhan-oss/DhanHQ-py](https://github.com/dhan-oss/DhanHQ-py) | 2026-10-08 | MIT | Official alternative with historical candles and market feeds. Account/auth semantics differ; current examples include capabilities outside this project's scope. |
| [FyersDev/fyers-api-sample-code](https://github.com/FyersDev/fyers-api-sample-code) | 2025-03-13 | No root licence identified | Example repository, not a demonstrated installable, tested SDK. v3 examples exist; do not confuse examples with production infrastructure. |
| [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | 2026-11-06 | AGPL-3.0 | Broad Indian broker/platform reference; much larger scope and order capability than this project needs. Borrow design ideas after review, not wholesale replacement. |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 2026-08-05 | AGPL-3.0 | Good independent strategy/backtest comparison tool. Indian charge rules, price bands, surveillance and corporate-action assumptions still need custom modeling. |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 2026-11-03 | Apache-2.0 + Commons Clause | Useful fast research grid/portfolio engine; many parameter trials increase selection risk. Current licence is not plain Apache-2.0. |
| [mementum/backtrader](https://github.com/mementum/backtrader) | 2023-04-19 | GPL-3.0 | Mature event-driven reference with commission/slippage hooks, but old default-branch commit and no automatic India-specific correctness. |
| [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | 2026-11-02 | Apache-2.0 | Best narrow addition to consider for offline portfolio metric/report parity. Feed verified returns; its win rate is a period win rate, not automatically a trade win rate. |
| [rsheftel/pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars) | 2026-10-31 | MIT | Useful second calendar opinion, not exchange authority. The inspected NSE calendar explicitly cannot represent weekend Muhurat sessions. |
| [quantopian/empyrical](https://github.com/quantopian/empyrical) | 2020-10-14 | Apache-2.0 | Compact metric formula reference, weaker choice as a fresh runtime dependency owing to old branch activity. |

- For stock-market-india, GitHub metadata says pushed_at 2023-12-17 and updated_at 2026-10-26, but the default branch's latest commit is 2021-12-14. This illustrates why repository stars and updated_at should not drive selection. Its package test script exits with a no-tests placeholder. Its NSE constants use www1.nseindia.com legacy JSP/JSON paths. There is also a concrete static inconsistency: service/API.js imports INDEX_CHARTDATA_URL, which the inspected constant.js never defines. We did not execute the package or assert that every endpoint fails today. [Metadata](https://api.github.com/repos/maanavshah/stock-market-india), [default commit](https://github.com/maanavshah/stock-market-india/commit/048b6c15b90553c426ebf266e1edfcc0e53fe750), [constants](https://github.com/maanavshah/stock-market-india/blob/048b6c15b90553c426ebf266e1edfcc0e53fe750/nse/constant.js), [service](https://github.com/maanavshah/stock-market-india/blob/048b6c15b90553c426ebf266e1edfcc0e53fe750/nse/service/API.js), [package](https://github.com/maanavshah/stock-market-india/blob/048b6c15b90553c426ebf266e1edfcc0e53fe750/package.json).
- NSEPython's current source uses curl_cffi/Chrome impersonation and has a browser-cookie helper. That design conflicts with this project's explicit no-bypass collection policy; no such transport was installed or used. Its get_beta constructs separate stock/index return arrays, then zips them without joining dates. This can mispair observations where histories differ, and there is no explicit date alignment in that calculation. A tutorial's beta function therefore cannot serve as a calculation oracle without independent tests. This is a library finding, not a finding that the user's code imports that function. [Pinned source, get_beta near lines 1948–1990](https://github.com/aeron7/nsepython/blob/32d82eafcedc3c6db880f83586be690e18f42814/nsepython/rahu.py).
- NseIndiaApi documents rate limiting, session handling, Retry-After handling, a v5 migration guide and broad corporate-filing methods. Those are useful engineering features, but its own advertised transport uses browser-like headers and cookies; default retry policy cannot simply replace the current once-per-file/day collector. [Pinned README](https://github.com/BennyThadikaran/NseIndiaApi/blob/b7fd7eb73f900986d327171d571952492663b31c/README.md).
- jugaad-data explicitly documents cached requests and functions for index total-return values. The user's direct NSE daily index file is a price-index source, so verified TRI intake is a plausible research gap. The current custom licence is saved locally; GitHub's metadata did not assign a standard SPDX licence. [README](https://github.com/jugaad-py/jugaad-data/blob/06b1bfd304afe78e72fadd2b0472761f59c6ddb5/README.md), [licence](https://github.com/jugaad-py/jugaad-data/blob/06b1bfd304afe78e72fadd2b0472761f59c6ddb5/LICENSE.YOLO.md).
- QuantStats documents that return-series win rate, payoff and profit factor are calculated across periods. Comparing those directly to this project's discrete trade statistics would create an apparent disagreement even if both implementations match their own definitions. [Metric semantics](https://github.com/ranaroussi/quantstats/blob/d1a214fb906e76f974f45cdccf923b601c67a756/README.md).
- vectorbt's inspected licence contains the Commons Clause restriction on selling software/services whose value derives substantially from the software. Preserve the exact version and review before a hosted/commercial derivative; do not label this licence simply Apache. [Pinned licence](https://github.com/polakowo/vectorbt/blob/c923f74c9e4d1e07e626ae9002f7382cd8264833/LICENSE.md).
- The inspected pandas-market-calendars NSE class states its 1996–2026 scope and weekend-Muhurat representation limitation. Never replace the current explicit NSE session rules with a generic Monday–Friday generator on that basis. [Pinned NSE calendar](https://github.com/rsheftel/pandas_market_calendars/blob/f511a67c0826065a1e880e4e32dd4f86be6840e7/pandas_market_calendars/calendars/nse.py).

### Inferences

The practical shortlist is **existing official exchange archives + existing narrow Kite adapter**, **QuantStats for independent return-series metric comparisons**, **backtesting.py for a small independent backtest cross-check**, and **NseIndiaApi/jugaad-data as references for missing filings/TRI data adapters**. NSEPython belongs in the learning/reference layer until its transport and formula assumptions are tested. For this project, OpenAlgo and broker alternatives solve different infrastructure choices; they do not fix ranking bias automatically.

Broker SDKs, exchange data wrappers, backtest engines and analytics libraries are four different layers. There is no meaningful single overall winner across them. A data wrapper does not have Zerodha account access, an official SDK does not supply a validated stock-selection model, and a backtest engine does not supply reliable point-in-time Indian security eligibility.

### Gaps

No third-party repository was installed, imported or executed. We did not run their test suites or benchmark latency, broker entitlements, uptime, quotas or fill quality. Root test directories/CI badges were inspected, not treated as evidence that all tests currently pass. Fyers licensing remained unidentified. This repository section does not claim paid broker data plans or course content were fully evaluated; those are covered by the parallel provider/course research.

## Does marketlab-integrity already use these approaches?

### Takeaway

**Yes: it already implements the key data architecture itself. No: the candidate libraries are not active dependencies in the inspected source.** Existing reference folders should not be described as integrations.

### Cited Findings

- marketlab-integrity/pyproject.toml has no required runtime dependencies; optional AI support uses anthropic. An AST scan of all Python files in src found no imports of nsepython, nsepythonserver, nse, jugaad_data, kiteconnect, upstox_client, dhanhq, fyers_apiv3, openalgo, backtesting, backtrader, vectorbt, quantstats, pandas_market_calendars or empyrical. The scan, source hashes and import roots are recorded in [local_integration.json](../../evidence/repos/local_integration.json). This is static source evidence, not an inspection of every installed environment.
- The existing [kite.py](C:/Users/d_hru/try/tradebot/marketlab-integrity/src/marketlab/kite.py) calls https://api.kite.trade directly through stdlib urllib. It allowlists holdings, positions, orders/trades **reads**, quotes, instruments and historical candles; its sole allowed POST is the login token exchange. The lack of a kiteconnect import does **not** mean Zerodha API integration is missing.
- The existing [sources.py](C:/Users/d_hru/try/tradebot/marketlab-integrity/src/marketlab/sources.py) already registers NSE equity master, security/band/surveillance files, UDiFF and legacy bhavcopies, delivery data, corporate-action and announcement RSS, holidays, index closes and BSE bhavcopy. It records URLs, timing assumptions, schema fields and known missingness. Importing another wrapper would duplicate much of this work.
- Existing reference_bots directories include pykiteconnect, openalgo, backtesting.py, vectorbt, backtrader, quantstats, exchange_calendars, Lean, Lean.Brokerages.Zerodha, nautilus_trader, zipline-reloaded, FinRL and others. These directory names alone prove downloaded references, not active use. The static scan above supplies the integration distinction. [Reference folder](C:/Users/d_hru/try/tradebot/reference_bots), [project dependency declaration](C:/Users/d_hru/try/tradebot/marketlab-integrity/pyproject.toml).
- Local AGENTS.md explicitly limits the project to cash-only NSE/BSE research and paper investing, prohibits order capability, says missing data remains unknown, and separates provider-adjusted prices from actual exchange prices. The independent adapter preserves those constraints. [Project instructions](C:/Users/d_hru/try/tradebot/marketlab-integrity/AGENTS.md).

### Inferences

Retain the narrow read-only network boundary. Using the official Kite SDK as a reference or inside a strict adapter may reduce protocol maintenance, but passing its unrestricted client to research code would widen capabilities unnecessarily. More libraries would not by themselves establish statistical validity or produce priority stocks.

Recommended staged integration: (1) keep provenance and independent parsing checks, (2) add dated filings/corporate actions and a documented TRI benchmark only where current coverage is missing, (3) compare existing metrics against a separately implemented oracle with matching conventions, (4) compare a frozen strategy's cashflows with a second backtest engine, (5) consider a second broker only after specifying data coverage, entitlement, timestamp and corporate-action acceptance tests.

### Gaps

The active tree is being edited concurrently. Hashes record what was observed, not a claim that the files remain unchanged. No credentials, .env values, account holdings or balance contents were read. Static import absence does not rule out scripts elsewhere invoking a package; this conclusion applies to the inspected active src and declared runtime dependencies.

## What data and implementation were delivered?

### Takeaway

A standalone **stdlib-only**, read-only public-data intake and validation module now runs in the new sibling folder. It downloaded real official data successfully and can revalidate everything offline. The one-session sample establishes ingestion reproducibility, not alpha, forecast calibration or a sufficient historical backtest.

### Cited Findings

| Source | Session/receipt scope | Observed result | Evidence |
|---|---|---|---|
| [NSE UDiFF cash bhavcopy](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261105_F_0000.csv.zip) | 2026-11-05, retrieved 2026-11-06 06:56:25 UTC | 209,545 compressed bytes; 3,726 source rows; 2,742 valid traded EQ/STK rows; 984 outside-scope rows explicitly recorded | data/receipts/nse_bhavcopy_2026-11-05_2026-11-06.json |
| [NSE current equity list](https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv) | Current snapshot retrieved 2026-11-06 06:56:26 UTC | 2,630 rows; 185,778 bytes | data/receipts/nse_equity_list_2026-11-06.json |
| [NSE corporate-action RSS](https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml) | Rolling feed retrieved 2026-11-06 06:56:26 UTC | 45 items; 17,783 bytes | data/receipts/nse_corporate_actions_2026-11-06.json |

- Data receipts contain exact URL, session or current-snapshot semantics, request/receipt UTC, HTTP status, Last-Modified, raw SHA-256, byte count, normalized SHA-256 where relevant, and rights caveat. Successful HTTP responses alone are insufficient: CSV/ZIP/XML schema and content validation must pass. No failed public requests occurred for the three real datasets. [Receipt folder](../../data/receipts).
- The normalized CSV schema is date,symbol,series,isin,open,high,low,close,volume,turnover. Decimal preserves exact source decimal prices; identity, finite numeric values, positive traded-price values, OHLC ordering, integer volume, duplicate date/symbol/series and session consistency are validated. Unsupported instrument/series rows are recorded separately; legitimate zero-volume rows are explicitly classified as no-trade observations, never manufactured into zero prices. [Implementation](../../src/data_pipeline.py), [tests](../../tests/test_data_pipeline.py).
- ZIP content is read in memory without extracting member paths. Source URLs are restricted to the official NSE archive host; redirects are refused; download sizes are capped; success/refusal is cached per source per UTC day. The malformed-download test verifies no normalized success is claimed and the refused retrieval is not retried that day. [Implementation](../../src/data_pipeline.py), [tests](../../tests/test_data_pipeline.py).
- Offline validation recomputes raw and normalized hashes, re-parses original bytes and checks equality with the saved normalized records. It rejects path traversal in receipt paths. All **11 independent tests passed** and all **three saved receipts passed offline validation** after the changes. [Tests](../../tests/test_data_pipeline.py).
- Source files and pinned READMEs were downloaded as evidence text only; no third-party package was executed, and no source project was changed. [Repository manifest](../../evidence/repos/repository_manifest.json).

Commands from C:/Users/d_hru/try/tradebot-india-audit:

```powershell
python -B -m unittest discover -s tests -p test_data_pipeline.py -v
python -B -m src.data_pipeline validate
python -B -m src.data_pipeline fetch --session 2026-11-05
```

The fetch command returns today's cached receipts for already requested sources. On a new day it creates a new raw vintage; use validate for purely offline work.

### Inferences

The sample is useful as a reproducible ingestion fixture and a second parser to compare against the main data layer. It intentionally does not estimate returns, rescore stocks, infer corporate actions from price ratios, or place trades. This avoids making a new data source appear to validate an untested trading decision.

### Gaps

- The current equity list is **not** a historical universe. Applying it retrospectively creates survivorship/listing bias.
- EQ/STK is an instrument/series filter, not proof that every row is an ordinary company equity; ETFs and other securities must be classified with dated identity data before strategy inclusion. The independent sample does not silently inner-join today's list to yesterday's panel.
- Bhavcopy prices are unadjusted exchange observations. This adapter applies no split, bonus, dividend, rights or merger adjustment. Keep corporate-action reconciliation explicit.
- RSS is a rolling recent feed, not complete corporate-action history, and its items were archived without converting purpose text into adjustment factors.
- Retrieval now and Last-Modified do not prove what was known at a historical decision time. publication_time remains null and historical_availability_proven remains false. Never insert this receipt timestamp into a past decision as if it had been known then.
- Public availability is not an open-data licence. No redistribution/commercial rights are inferred; data stays in the local research folder.
- There is only one trading session in this independent sample. The main project's multi-session history remains the source for the separate calculation and selection audit; this sample does not establish strategy profitability.

