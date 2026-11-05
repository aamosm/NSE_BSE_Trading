# NSE historical pilot, January–July 2025

**Branch:** `historical-pilot`, built on `integrity-replay`. Produced 5 Nov 2026 by Claude Opus 5.5.

**Data and provenance**
- Data folder: `data/pilot/nse_2025/`. It is git-ignored, 36 MB, and these files are not redistributed.
- Immutable manifest: `docs/pilot/nse_2025_manifest.json`, a copy of `data/pilot/nse_2025/manifest.json`.
  - File SHA-256: `93501484…6ba4d25`.
  - Content hash: `42d142f4…a4be64`.
  - Re-verified: every stored file re-hashed, 0 problems.
- Reports are written once, as `report.json`, `report-2.json` and `report-3.json`. Each later version states what it supersedes. **v3 is current** (`a2fdffb4…9a63955`).

**Rerun commands**

    python scripts/pilot_acquire.py data/pilot/nse_2025 2025-01-01 2025-07-31   # idempotent; stored files are not refetched
    python scripts/pilot_report.py  data/pilot/nse_2025 2025-01-01 2025-07-31   # verifies the manifest, writes the next report version

The final holdout was not frozen or opened. Nothing here is a strategy result.

## 1. Acquisition and provenance

- **Routes used:**
  - official NSE archive files only (`nsearchives.nseindia.com`): UDiFF bhavcopy, `ind_close_all`, `sec_list` and `REG1_IND`, for every calendar day in the window (bhavcopy only on weekends);
  - the legacy bhavcopy for 3–8 Jul 2024;
  - two NSE-hosted Infosys filings.
- **Request pace and volume:** 1.5 s apart. 671 attempts gave 584 files stored, 87 not published (404), 0 failed and 0 schema failures.
- **Duplicate requests:** five probe requests made before the collector ran duplicate one collector request each. This is disclosed in the manifest.
- **Three times are kept apart for every file:**
  - `received_at`: actual local receipt, 5 Nov 2026. It is never backdated.
  - `server_last_modified`: the exchange server header.
  - `reconstructed_available_at`: the server time when it falls within 4 days of the file's date, otherwise unknown.
- All 584 files carry server-time evidence. Median server times:

| File | Median server time (IST) |
| --- | --- |
| bhavcopy | 16:32 |
| sec_list | 17:50 |
| REG1_IND | 19:00 |
| index closes | 23:20 |

- A rule file is used in replay only if its server time precedes the entry session's open.

## 2. Sessions: expected and observed

- There is no verified 2025 calendar, so sessions are reconstructed from publication (basis `OBSERVED_PUBLICATION`).
- There are **146 sessions, all stored for all four sources**, with no missing interval and no weekday of unknown status.
- **Weekday closures observed (404):** 26 Feb, 14 Mar, 31 Mar, 10 Apr, 14 Apr, 18 Apr and 1 May 2025.
- **Weekend session observed:** Saturday 1 Feb 2025 (Budget day).
- GPT must confirm all of this against the 2025 circular (Q1).

## 3. Format transition (verified before scaling older history)

- The legacy CSV and UDiFF exist for 3, 4 and 5 Jul 2024. The legacy file is 404 from 8 Jul 2024.
- On all three overlap days the same rows appear in both (2,800, 2,792 and 2,775), with 1,906–1,911 EQ rows.
- There are **0 mismatches** over open, high, low, close, base price, volume, value and trades.
- The legacy file lacks the security name, so ETF detection there falls back to the INF ISIN prefix.

## 4. Finding: exchange base prices are not adjusted on ex-dates

The spec (§2.4) assumed `PrvsClsgPric` on an ex-date is the exchange-adjusted base price, giving an implied factor. **In these files it is not.**

| Case | Base price | Close | Interpretation |
| --- | --- | --- | --- |
| IGL, 31 Jan 2025, 1:1 bonus | 395.70 | 201.80 | ratio 0.51 |
| SHRIRAMFIN, 10 Jan 2025, 5:1 split | 2,809.85 | 532.00 | the split also issued a new ISIN (INE721A01013 → INE721A01047) |
| INFY, 30 May 2025 (₹22 dividend ex-date per a secondary source) | 1,585.60 | — | equals the previous close: no adjustment |

Across seven months and about 3,000 securities, the implied-factor method found **1** factor. The new detection finds:
- **30 ISIN replacements** under an unchanged symbol (SENCO, SHRIRAMFIN, NAUKRI, BAJFINANCE, COFORGE and others);
- **196 one-session jumps** outside [0.795, 1.255]. 20 of them were in the investable universe the session before:
  - bonuses: IGL, ASHOKLEY, MOTHERSON, VMART;
  - demergers: SIEMENS, RAYMOND, ABFRL;
  - apparent genuine crashes: INDUSINDBK on 11 Mar, IEX on 24 Jul. These are identified from public knowledge, not verified here.

**Consequences, all implemented:**
- Labels whose window crosses a jump are excluded as `PRICE_DISCONTINUITY_UNEXPLAINED`. Labels crossing an ISIN replacement are excluded as `IDENTITY_CHANGE`, not as a suspension.
- Feature windows containing a jump are incomplete.
- The ledger flags held positions with `IDENTITY_CHANGED` or `PRICE_DISCONTINUITY_UNEXPLAINED`.
- Excluding genuine crashes biases labels upwards. Only an official action history (Q2) removes that bias. H-CA1 (dividends in the base price): **no** in the one case observed (Q3).

## 5. Coverage by horizon (decision days 28 Jan–31 Jul; first 19 sessions lack 20-session screen history)

| | h = 5 | h = 20 | h = 60 |
| --- | --- | --- | --- |
| Resolved labels on eligibility-verified days | 94,362 | 81,921 | 50,166 |
| Decision-day range of those labels | 28 Jan – 23 Jul | 28 Jan – 2 Jul | 28 Jan – 7 May |
| Excluded: price discontinuity | 96 | 330 | 526 |
| Excluded: ISIN replacement | 19 | 49 | 124 |
| Excluded: no trade at the exit (delisting or suspension) | 5 | 20 | 37 |
| Excluded: no trade at entry | 5 | 5 | 5 |
| Unresolved (exit beyond 31 Jul) | 4,864 | 17,026 | 48,493 |
| Folds possible (needs 1,125 sessions + 251 of features) | 0 | 0 | 0 |
| Admissible for promotion | 0 | 0 | 0 |

- 126 of 146 decision days have verified eligibility: 19 lack history, and 1 lacks a rule file.
- The median universe is 774 securities.
- **Admissible for promotion is 0** because the sessions are observed rather than calendar-verified, there is no feature history, and no fold fits. The labels are usable for diagnostics only.

## 6. Reconstructed case: Infosys Q4 FY25 (no contemporary forecast exists, so it is labelled RECONSTRUCTED)

**Known beforehand**
- Board-meeting intimation, NSE-hosted PDF, server time 14 Mar 2025 16:19 IST.
- The filing records the intimation date as 14 Mar 2025 and the meeting as 17 Apr 2025, 14:00–16:10 IST.

**Facts (NSE-hosted integrated filing, server time 17 Apr 2025 23:36 IST)**
- INFY, INE009A01021, consolidated, audited, period 1 Jan–31 Mar 2025.
- Presentation in INR actuals, rounded to crores.
- Revenue from operations ₹409,250,000,000 (₹40,925 crore). Net profit ₹70,380,000,000 (₹70,330,000,000 to owners). Basic EPS ₹16.98.
- Unit check: "40,925 crore" passes; "409,250,000,000 crore" fails.

**Earliest usable decision:** after 23:36 IST on 17 Apr, from the filing's server time. The exchange's own announcement time is not held (Q4). That does not change the first fill:
- 18 Apr was a closure (observed 404);
- 19–20 Apr were a weekend;
- so the **earliest simulated fill was the 21 Apr 2025 open**.

**Inputs for that decision**
- Bhavcopy of 17 Apr: server time 16:32.
- sec_list: 20:40. REG1_IND: 20:50. Both are dated 17 Apr and describe 21 Apr, and both precede the 21 Apr open, so they are admitted.
- Eligibility: INFY was in the universe; series EQ; no band (F&O); no surveillance, suspension or call auction; 20-session median traded value ₹1,509.6 crore (0.10% slippage tier).

**Benchmark and label (h = 20)**
- Nifty 50 price index, open to open: 23,949.15 → 24,996.20 (+4.37%).
- INFY open ₹1,410.00 on 21 Apr → ₹1,570.00 on 20 May: gross +11.35%, excess +6.47% (log). Basis VERIFIED: no action or discontinuity in the window.
- All official values equal the review's secondary values: close ₹1,419.50 on 17 Apr, the two opens and both index opens.

**Successful trace (ledger, EXEC.v1)**
1. Intent after the 17 Apr close: 3 shares, the most at a ₹5,000 cap from the ₹1,419.50 close. Limit ₹1,490.48; cash blocked at the limit.
2. Filled 21 Apr at ₹1,411.41 (buy value ₹4,234.23).
3. Expiry review after the 19 May close: no forecast, so EXIT.
4. Sold 20 May at ₹1,568.43 (₹4,705.29).

| Gross at the opens | Slippage | Charges (buy 4.79, sell 5.17, DP 15.34) | Net |
| --- | --- | --- | --- |
| ₹480.00 | ₹8.94 | ₹25.30 | **₹445.76 (10.52%)** |

Proceeds were unsettled until the next session.

## 7. Blocked traces

| Case | What happened | Ledger result |
| --- | --- | --- |
| **SENCO**: decided 28 Jan, filled 29 Jan, 5 shares | The ISIN INE602W01019 was replaced on 31 Jan by INE602W01027 (a split). The old ISIN never traded again. | Flagged `IDENTITY_CHANGED`. The exit was decided 24 Feb and blocked for 106 sessions. At period end it is EXIT_BLOCKED with bounds ₹0–₹4,481.48. The real outcome (more shares of the new ISIN) needs the action ratio. |
| **ISEC**: decided 19 Feb, filled 20 Feb, 5 shares | Last bar 21 Mar 2025. Likely the delisting on the merger into ICICI Bank (public knowledge, unverified here). | The exit was blocked for 89 sessions. At period end it is EXIT_BLOCKED with bounds ₹0–₹4,450.29. The real outcome is a share swap that the ledger cannot model without the scheme terms. |

## 8. Missing sources (details and precise questions in `GPT_SOURCE_QUESTIONS.md`)

1. The 2025 NSE holiday circular. Sessions are observed, not verified, so nothing here can support promotion.
2. An official corporate-action history with ratios, record and ex-dates. This is now critical, because base prices are not adjusted.
3. Dividend treatment and the official INFY ex-date.
4. The exchange announcement timestamps for results.
5. REG1_IND field definitions.
6. An archive of the historical equity list or listing events.
7. A Nifty 50 total-return series.
8. Archive start dates for sec_list and REG1_IND, and legacy bhavcopy coverage from 2016.
9. Rights and terms of use.

Also not collected: delivery data (`sec_bhavdata_full`), BSE files, and company-website documents (not exchange hosts).
