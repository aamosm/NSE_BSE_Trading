# Data inventory

Checked 4 November 2026. "Have" means the data is in this repository now. Nothing here is a licence to scrape or redistribute: each source's terms must be checked before automated collection (Phase 2).

## 1. What we have now

| Data | Form | Coverage | Provenance |
| --- | --- | --- | --- |
| NSE 2026 trading and settlement holidays | Hand-transcribed into `rules/calendar.py` | 2026 only | NSE circulars (RULES_REGISTER §1). The 16 trading holidays independently match `exchange_calendars` XBOM 2026 |
| Session regimes (pre-open, CAS, post-close) | `rules/sessions.py` | Rules effective-dated from 2026-08-03 / 2026-09-07 | NSE/SEBI circulars |
| Tick-size table | `rules/ticks.py` | From 2024-06-10 (secondary) and 2025-04-15 (primary) | NSE circular |
| Series/group and surveillance stage rules | `rules/instruments.py` | Rules only, **no lists of which stocks are in which stage** | NSE circulars, Zerodha pages |
| Zerodha charges, MTF terms, API limits | `rules/charges.py`, `mtf.py`, `broker.py` | Snapshot observed 2026-11-04. Earlier dates are counterfactual | Zerodha pages |
| Market data | **None** | — | — |
| Account data (holdings, trades, statements) | **None**, deliberately (kept out of Git) | — | — |

## 2. Daily inputs the rules engine needs (`InstrumentSnapshot`)

Each field is required for a decision. A missing field blocks the order with a `*_UNKNOWN` reason code.

| Field | Candidate source | Published | Notes and open questions |
| --- | --- | --- | --- |
| ISIN, symbol, series/group | NSE security master / bhavcopy; Kite `instruments` dump (daily CSV) | Daily before open | Series changes (EQ↔BE) are how T2T moves happen. Store history |
| Base price (previous close/adjusted) | NSE bhavcopy; Kite instruments `last_price` (not authoritative) | After close | Corporate-action adjusted base on ex-dates |
| Static price band % | NSE "price band" file (sec_list) | Daily | Bands change with surveillance actions |
| F&O membership | NSE F&O underlying list | Monthly/ad hoc | Drives CAS (from 2026-08-03), dynamic bands, MIS cut-off |
| Tick size | Kite instruments `tick_size`; derived from the 2025 table and month-end price | Daily | Engine warns if the two disagree |
| Surveillance stages (GSM, ESM, ASM LT/ST, IBC, USM, low NPH) | NSE surveillance pages / downloadable lists | Daily or weekly per framework | **Historical lists are the biggest gap.** We cannot reconstruct past stages without an archive |
| Periodic call auction, suspension, special pre-open | NSE circulars / market notices | Ad hoc | |
| MIS eligibility | Zerodha intraday list | Daily | Broker-specific |
| MTF approved list and VaR/ELM | Zerodha MTF list; NSE/NCL VaR margin files | Daily | Current lists only. Historical MTF eligibility is not available, so older replays are counterfactual |
| Nifty 500 membership | NSE index constituents | Semi-annual + ad hoc | For MTF per-stock caps |
| LTP / quotes | Kite quotes or WebSocket (Phase 7) | Live | Needed for market-protection limits |
| CAS reference price | Exchange during 15:15–15:20 | Live | Only if trading in CAS (policy currently limit-only) |

## 3. Data we need for research (Phases 2–5)

| Data | Why | Free/permitted candidates | Status |
| --- | --- | --- | --- |
| Daily OHLCV with volume and delivery % | Prices, liquidity | NSE bhavcopy archives; Kite historical (₹500/month Connect) | Terms to check; not collected |
| Corporate actions with announcement, record and ex-dates | Adjustments, PIT correctness | NSE/BSE corporate-action pages | Not collected |
| Filings and announcements **with publication timestamps** | Event features | NSE/BSE announcement feeds (S18, S19) | Not collected; BSE page returned an access error earlier |
| Fundamentals as originally published, plus revisions | Valuation features without hindsight | Original filings (XBRL) or licensed PIT vendor | **Likely needs a licence**; cost unknown |
| Historical index constituents | Survivorship-free universe | NSE index factsheets/notices | Partial; to be assembled |
| Delistings and symbol changes | Universe and P&L must not drop dead stocks | NSE/BSE notices | Not collected |
| Historical surveillance stages, series changes | Replay legality | NSE notices (archive depth unknown) | **Gap**; replays without them must be labelled |
| 91-day T-bill cut-off yields | Risk-free rate in Sharpe/Sortino | RBI auction results | Not collected |
| Benchmark: Nifty 50 TRI and an ETF price | Baselines | NSE indices; ETF bhavcopy | Not collected |
| Historical Zerodha charges/MTF terms | Non-counterfactual cost replays | Zerodha change notices | Only the 2026-11-04 snapshot exists |

## 4. Point-in-time requirements (apply to every dataset)

1. Each observation stores `event_time`, `published_at` (when knowable; else `NULL`, never midnight), `ingested_at`, `effective_from/to`, `source_id`, `source_hash` and `revision_of`.
2. Queries take an explicit `as_of` cutoff and see only rows with `published_at ≤ as_of`. Rows with unknown publication time are excluded from decisions until a policy decides otherwise.
3. Corrections append new rows linked to the old one (qlib-style `_next`). Old decisions keep pointing at the version they used.
4. Corporate actions apply to prices and positions on the ex-date. The raw unadjusted series is kept.
5. Universe membership is historical. Delisted and renamed instruments stay in the store.

## 5. Account data (Phase 7, user action required)

Holdings, positions, funds, trades and order updates via the official Kite API after the user logs in. Contract notes, tax P&L and the MTF/EQ ledger statements come from Console downloads that the user places in `data/private/` (git-ignored). These statements resolve RULES_REGISTER §10 items: the MTF interest day-count, charge rounding and DP timing.
