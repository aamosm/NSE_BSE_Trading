# Source status

Verified by real retrievals from the Windows laptop on 5 November 2026 (00:37–01:30 IST). Each route was fetched without cookies, logins or anti-bot workarounds, using a plain browser-style User-Agent. The machine-readable register is `src/marketlab/sources.py` (`REGISTER`, `NOT_COLLECTED`). Every collection attempt is recorded in `data/market/catalog.sqlite3`, failures included.

**Rights.** The exchange website terms of use have **not** been reviewed in full. Current use is personal, non-redistributed research at one request per file per day. Do not publish or resell these files. Review the terms before any wider use.

## 1. Official exchange files (collected)

| Source id | Route | Result 5 Nov | Archive depth (spot-checked) | Timing and semantics |
| --- | --- | --- | --- | --- |
| `nse_equity_list` | `nsearchives…/content/equities/EQUITY_L.csv` | 200, schema OK | **Current list only** | No publication time. Listing date, ISIN, face value, lot. Delisted securities disappear: history exists only in our daily vintages |
| `nse_sec_list` | `…/content/equities/sec_list_DDMMYYYY.csv` | 200 | ≥ 3 Jan 2022 | Last-Modified **18:01 IST** on the dated day, i.e. after its close. Describes the **next** session (see §4) |
| `nse_band_changes` | `…/content/equities/eq_band_changes_DDMMYYYY.csv` | 200 (3 rows) | not checked | After close; effective date not in the file |
| `nse_reg_indicators` | `…/content/cm/REG1_INDDDMMYY.csv` | 200 (3,224 rows) | ≥ 2 Jan 2025 | After close; next session. `/content/equities/` path → 404 |
| `nse_bhavcopy` | `…/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` | 200 | UDiFF ≥ 5 Jul 2024 | End of day. Actual traded prices. Includes ISIN and FinInstrmId |
| (older format) | `…/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip` | 200 for 5 Jul 2024 and 4 Jan 2016 | ≥ 4 Jan 2016 | Pre-UDiFF layout; **parser not written yet** |
| `nse_bhavdata_full` | `…/products/content/sec_bhavdata_full_DDMMYYYY.csv` | 200 | ≥ 2 Jan 2020 | Adds delivery quantity/percentage; no ISIN column |
| `nse_fo_mktlots` | `…/content/fo/fo_mktlots.csv` | 200 | **Current only** | F&O underlyings, used for `has_derivatives` |
| `nse_indices_close` | `…/content/indices/ind_close_all_DDMMYYYY.csv` | 200 | ≥ 2 Jan 2020 | Index OHLC, P/E, P/B, dividend yield. **Price** indices, not total return |
| `nse_rss_corporate_actions` | `…/content/RSS/Corporate_action.xml` | 200 (36 items within 14 days) | Rolling window | Company **name**, ex-date, record date, purpose text. No symbol, ISIN or payment date |
| `nse_rss_announcements` | `…/content/RSS/Online_announcements.xml` | 200 | Rolling, short | Items are lost unless collected often (scheduler: every 30 min) |
| `nse_rss_financial_results` | `…/content/RSS/Financial_Results.xml` | 200 | Rolling | Links only |
| `nse_rss_board_meetings` | `…/content/RSS/Board_Meetings.xml` | 200 | Rolling | Results dates |
| `nse_holidays` | `www.nseindia.com/api/holiday-master?type=trading` | 200 JSON | Current year | Worked without cookies today; may change |
| `nse_clearing_holidays` | `…/api/holiday-master?type=clearing` | 200 JSON | Current year | Settlement holidays |
| `bse_bhavcopy` | `www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV` | 200 | ≥ 8 Jul 2024 | `SctySrs` = BSE group, the fee-group source |
| NSE circulars | `nsearchives…/content/circulars/<ID>.pdf` | 200 (CMTR76941, CMPT77037, INSP45900) | — | The web-fetch tool timed out on these; direct download worked |

## 2. Kite Connect (owner's paid plan)

Successful reads on 4 and 5 Nov 2026:
- profile and token exchange;
- holdings, positions, trades and equity margins;
- NSE/BSE instrument dumps;
- `/quote`;
- daily historical candles (INFY, 22 bars).

On 5 Nov a full collection **batch** completed (status COLLECTED). Rate limits are documented: quotes 1/s, historical 3/s, others 10/s. The adapter uses one request per 1.05 s for everything.

- **Historical candles are adjusted by Zerodha** for bonus, split, rights, spin-off and extraordinary (≥ 2%) dividends, before the ex-date open. Volume is adjusted except for dividends. There is no corporate-action API (KITE/CA-ADJUSTMENT, KITE/CA-FORUM-15971). Stored as `PROVIDER_ORIGINAL` with a retrieval vintage. Never treated as actual traded prices.
- `PermissionException` is not on Kite's exceptions page but is defined by the official client library. It is kept in the enumerated set.

## 3. Not collected (and why)

| Item | Status | Reason |
| --- | --- | --- |
| BSE holiday notice | BLOCKED (earlier session) | Retrieval refused; the BSE calendar stays unloaded |
| BSE scrip master, surveillance and bands | NOT_ATTEMPTED | `api.bseindia.com` expects browser headers; not attempted, to avoid bypassing controls |
| NSE corporate-action and announcement **history** | NOT_ATTEMPTED | `www.nseindia.com/api/corporates-*`; only the RSS rolling window is collected |
| NSE financial results (XBRL) | NOT_ATTEMPTED | Needed for company economics (next milestone) |
| Historical F&O membership | NOT_ATTEMPTED | Could be reconstructed from F&O bhavcopy archives |
| Zerodha MIS eligibility list | NOT_AVAILABLE | No API; the intraday paper sleeve stays blocked |
| Historical bid/ask depth | NOT_AVAILABLE | Current depth cannot reconstruct the past; Kite quotes are collected prospectively only |
| Licensed news | NOT_PURCHASED | Not justified until `DATA_READINESS.md` shows a specific gap it closes |

## 4. Findings from the real files

1. **After-close files describe the next session.** On 4 Nov 2026, three securities changed series against that day's bhavcopy: 21STCENMGM EQ→BE, MILTON SM→ST and RAVITA ST→SM. All three appear identically in both `sec_list_04112026` and `REG1_IND041126`. For session D the builder therefore takes series, band and surveillance from the previous trading day's files, and blocks if the two files disagree.
2. **Regulatory-indicator codes.** Value `100` means the measure does not apply; otherwise the value is the stage. The GSM column matches the sec_list remarks for every overlapping row (cross-checked).
   - `Status` S = suspended (16 rows) and `ICA` = periodic call auction are **assumptions** from column names. No NSE field definition was found.
3. **Calendar.** The engine's NSE 2026 trading holidays (16 weekdays) and settlement holidays (20) **agree exactly** with NSE's holiday APIs (`marketlab verify-calendar`). This includes the ad hoc 15 Jan closure that earlier came only from a mirror.
4. **Security master for 5 Nov:**
   - 2,627 NSE and 5,044 BSE listings;
   - 2,434 ISINs on both exchanges;
   - 0 ISIN conflicts between the NSE list and bhavcopy;
   - 14 NSE listings without a previous-session code (not traded on 4 Nov).
5. **Muhurat.** NSE/CMTR/76941 (session table) and NCL/CMPT/77037 (8 Nov trades settle 9 Nov, M 2026211) were read in full and encoded.
6. **STT.** Zerodha documents nearest-rupee rounding but not the aggregation level. NSE/INSP/45900 shows contract-note STT is an integer field. The aggregation basis (per client, security and day) comes from a third-party copy of the 2004 draft rules, so it stays an ASSUMPTION until checked against one real contract note.

## 5. Next acquisition work (in order)

1. Backfill the UDiFF bhavcopy (Jul 2024 →) and the old-format bhavcopy (2016 →), with a parser for the old layout. Throttle to one file per 1.5 s, resumable through the catalog.
2. Backfill sec_list (2022 →) and REG1_IND (2025 →) for point-in-time rule inputs.
3. Collect the official corporate-action history (NSE corporate-actions page/API, if retrievable without bypass). Until then, use bhavcopy previous-close discontinuities only to **flag** ex-dates, never to infer ratios.
4. NSE announcement timestamps and financial-result filings for the earnings-event family.
5. BSE calendar, bands and surveillance from BSE's own published notices.
