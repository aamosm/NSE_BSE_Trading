# Data readiness

Status 5 November 2026. This answers one question: **what can be modelled honestly with data that exists today, and what blocks the rest?**

It is the input to Fable session 1. "Stored" means held locally with receipt times. "Archive" means an official archive was spot-checked and can be backfilled, but **has not been downloaded yet**.

Bottom line: **no horizon is testable today.**
- Exchange prices can be backfilled years deep, so swing and core price-only research becomes testable after a backfill.
- That backfill also needs corporate actions, which are the main blocker.
- Intraday, earnings-event and new-listing research need data that is not yet collectable.

## 1. Coverage by layer and field

| Layer | Field | Stored now | Archive available (spot-checked) | Point-in-time quality | Blocker |
| --- | --- | --- | --- | --- | --- |
| Identity | ISIN, symbol, series, exchange code (NSE) | 5 Nov 2026 vintage | Current list only; bhavcopies carry ISIN and series daily | Good from bhavcopies; listings dated by first appearance | Delisting/rename lineage not built |
| Identity | BSE scrip code, group | 4 Nov 2026 | BSE UDiFF from Jul 2024 | Good for traded days | BSE master not collected |
| Identity | Kite instrument token | Daily dumps since 4 Nov (private) | none | Current only | Join through exchange code |
| Identity | Corporate-action lineage (ISIN changes) | — | — | — | Needs the official action history |
| Rules | Trading/settlement calendar NSE | 2026, **verified against NSE APIs** | Current year from API; older years need circulars | Good for 2026 | 2027 not published; pre-2026 not loaded |
| Rules | BSE calendar | — | — | — | BSE notice blocked; BSE simulations block |
| Rules | Session tables incl. special sessions | Regular regimes since 27 Jan 2023; Muhurat 2026 | — | Good | Older special sessions not loaded |
| Rules | Static band, series (next session) | 4 Nov file | sec_list from 2022 | Good; after-close timing observed | Backfill pending |
| Rules | Surveillance stages, suspension, call auction | 4 Nov file | REG1_IND from Jan 2025 | Stages cross-checked; suspension and call-auction mapping ASSUMPTION | Before 2025: no source found |
| Rules | F&O membership | 5 Nov vintage | Current only | Current only | History via F&O bhavcopy (not attempted) |
| Rules | Tick reference close | 30 Oct 2026 bhavcopy | yes (bhavcopy) | Good | — |
| Rules | Broker MIS eligibility | — | — | — | Not available; intraday paper sleeve blocked |
| Prices | Daily OHLCV, actual (NSE) | 30 Oct and 4 Nov 2026 | UDiFF from Jul 2024, old format from 2016 or earlier | Good (end of day; available after close) | Backfill and old-format parser pending |
| Prices | Delivery quantity | 4 Nov | from 2020 | Good | Backfill |
| Prices | Daily OHLCV, Kite | INFY Oct 2026 (22 bars) | Kite history | **Adjusted by Zerodha**, vintage-dependent | Use only as PROVIDER_ORIGINAL; reconcile with bhavcopy |
| Prices | Intraday bars | — | Kite minute history (adjusted) | Adjusted, not exchange-original | No unadjusted intraday archive |
| Prices | Bid/ask, depth | — | none | Prospective only | Must be collected forward |
| Prices | Corporate actions (type, ratio, ex/record/payment dates) | RSS rolling window (5 Nov) | not found yet | Ex-date and purpose text only | **Main blocker** for returns across ex-dates and integer quantities |
| Company economics | Financial results, cash flow, debt, dilution, ownership, pledges | — | NSE filings (XBRL), not attempted | — | Not collected |
| Events | Earnings/announcement times | RSS from 5 Nov | API history not attempted | Publication time from pubDate | History missing; prospective collection running |
| Events | Board meetings | RSS from 5 Nov | — | — | History missing |
| New listings | Listing date, series | Current equity list | first bhavcopy appearance | Good | Offer documents, float and lock-ups not collected |
| Context | Index levels (Nifty, sectors), P/E, P/B, yield | 4 Nov | from 2020 | Price index only | Total-return index missing; dividends needed for a fair benchmark |
| Account | Holdings, positions, trades, funds | 4–5 Nov (private) | none | Batch-consistent since 5 Nov | Contract notes and funds statement not imported |

## 2. Horizon readiness

| Horizon / family | Testable today? | What makes it testable | Cost hurdle at this capital (round trip, NSE) |
| --- | --- | --- | --- |
| Established companies, core (60–250 sessions) | **No** | Bhavcopy backfill from 2016 + official corporate actions + survivorship-aware universe (from bhavcopy archives) + total-return benchmark. Fundamentals add financial filings | ₹10,000 position: ₹37.60 (0.38%). ₹2,000: ₹19.78 (0.99%) |
| Swing (5–20 sessions), price/volume | **No** | Same backfill; sec_list/REG1_IND backfill for tradability on each date (2022/2025 onward) | Same as above, paid each trip; the ₹15.34 DP is about 0.77% of a ₹2,000 position |
| Company events (earnings) | **No** | Announcement timestamp history and filing contents; prospective RSS collection started on 5 Nov | As above, plus the reaction already in the price |
| New listings | **No** | Offer documents, float/lock-ups, a comparable-listing set. Listing-day special pre-open stays blocked | As above |
| Intraday | **No, and not soon** | Unadjusted intraday prices, bid/ask, the broker MIS list. Only prospective quote collection is possible | ₹10,000: ₹11.14 (0.11%) before spread and slippage |

Cost figures come from `rules.charges.day_charges` (Zerodha snapshot of 4 Nov 2026, STT rounded to the rupee per security-day). They are unreconciled with a real contract note.

## 3. Survivorship and look-ahead risks to design around

- `EQUITY_L` lists only current securities. A universe built from it has **survivorship bias**. Daily bhavcopies list every security traded that day, including ones later delisted, so the historical universe must come from bhavcopy archives.
- Kite history is re-adjusted after each corporate action. A download today shows prices nobody could trade at before the action. Only exchange bhavcopies are actual prices.
- Revised financials, current index membership and current F&O lists leak the future when applied to past dates.
- An LLM's background knowledge cannot be certified free of later events. Reconstructed datasets must be labelled reconstructed, and results need prospective confirmation.

## 4. Unblock order

1. Bhavcopy backfill: UDiFF, then old format with a new parser.
2. sec_list and REG1_IND backfill.
3. Official corporate-action history and a reconciliation of five representative actions (split, bonus, extraordinary dividend, ordinary dividend, rights) between Kite and bhavcopy prices, using `corporate_actions.reconcile_provider`.
4. Total-return benchmark (index + dividends) or an ETF price series.
5. Announcement and filing history for one liquid stock's earnings path (the first end-to-end family, per the plan).

Purchased data is justified only when a row above names the exact field and history it would fill, the strategy it unlocks, its rights and its cost. No such case exists yet.
