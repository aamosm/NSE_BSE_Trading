# Rules register: NSE/BSE cash equities at Zerodha

> **Active scope (4 Nov 2026):** NSE/BSE cash equities only, with read-only Kite data. MTF, borrowing and derivatives are removed, and the engine has no MTF product. Every paper proposal must pass this engine (`research.paper_proposal`). Without a dated security snapshot it abstains with `EXCHANGE_RULES_NOT_CHECKED`.


Checked: 4 November 2026; Muhurat, STT basis, DP and corporate-action sources added 5 November 2026. Code: `src/marketlab/rules/`. Tests: `tests/`.

Every rule below is encoded in the rules engine with a source ID and a status. The engine (`evaluate_order`) runs all checks and returns every PASS/WARN/BLOCK with its reason code, so a rejection can always be explained from recorded values.

## Status legend

| Status | Meaning | Engine treatment |
| --- | --- | --- |
| PRIMARY | Read in an NSE, NSE Clearing or SEBI document | Enforced |
| BROKER_OFFICIAL | Read on Zerodha's own support/docs pages. Broker policy can change without a circular | Enforced |
| SECONDARY | Seen only in a third-party summary or search snippet | Enforced conservatively; must be confirmed before live use |
| CONFLICTING | Sources disagree | The more restrictive reading is enforced |
| ASSUMPTION | Our modelling choice; no source states it | Enforced; must be reconciled against statements |
| UNKNOWN | Not determined | Blocks wherever the input is required |

Unknown required inputs never default to permissive values. Examples: a snapshot without surveillance lists, an unloaded calendar year, or an unknown F&O status.

## 0. What a low share price actually changes

Price alone does not stop a stock trading intraday. The restrictions people associate with "penny stocks" come from classifications that often coincide with low prices and small market caps:

- **Trade-for-trade (T2T)** series. On NSE that is BE/BZ; on BSE it is T/XT. Every trade must be delivered, so no intraday and no same-day sale. Section 3.
- **Surveillance stages** (GSM, ESM, IBC, ASM). These bring narrower bands, 100% margins, buyer deposits, once-a-week trading and "no upward movement". Section 4.
- **Periodic call auction** for illiquid stocks: no continuous trading at all.
- **Broker lists**: Zerodha's intraday (MIS) list excludes low-liquidity, narrow-circuit and high-margin stocks.

What price itself changes:

- Tick size is ₹0.01 below ₹250 and larger above it.
- The exchange's market-order protection floor is a flat ₹1.50 when the last traded price (LTP) is ₹50 or below, and 3% above ₹50.
- A ₹20 cap or ₹15.34 DP fee is a large percentage of a small trade (section 8).

## 1. Calendar and settlement

**Budget Sunday, 1 Feb 2026:** a full live trading session at standard timings: pre-open 09:00–09:08 and normal market 09:15–15:30. Its trades settled T+1 on 2 Feb, and 1 Feb itself was a settlement holiday with no T0 session. Modelled as a weekend trading day, which makes NSE 2026 246 regular sessions. Sources: NSE/CMTR/72349 (16 Jan 2026) and NCL/CMPT/72384 (19 Jan 2026), both PRIMARY. Added after independent review finding R10.

| Rule | Value | Effective | Status | Source | Engine |
| --- | --- | --- | --- | --- | --- |
| Settlement cycle | T+1 rolling for all securities | 27 Jan 2023 | PRIMARY | NSE/CMTR/73927 §1.5 | Dates before this raise `RuleUnknown` |
| Settlement date | First settlement working day strictly after the trade date | — | PRIMARY (derived) | NCL/CMPT/71904 | `settlement_date()` |
| 2026 trading holidays | 26 Jan, 3 Mar, 26 Mar, 31 Mar, 3 Apr, 14 Apr, 1 May, 28 May, 26 Jun, 14 Sep, 2 Oct, 20 Oct, 10 Nov, 24 Nov, 25 Dec | 2026 | PRIMARY | NSE/CMTR/73927 §2.1 | `MARKET_HOLIDAY` |
| Ad hoc closure | 15 Jan 2026 (trading and settlement holiday) | 2026 | SECONDARY | NSE circular title via mirror | Loaded; read NSE original |
| 2026 settlement-only holidays (exchange open) | 19 Feb, 19 Mar, 1 Apr, 26 Aug | 2026 | PRIMARY | NCL/CMPT/71904 | BTST blocked on these days |
| Muhurat session | Sunday 8 Nov 2026: pre-open 14:05–14:10 limit+market, 14:10–14:15 limit only (random close in the last 2 min), matching/buffer to 14:20; normal market 14:20–15:30 (15:15 for CAS stocks); CAS 15:15–15:35; post-close 15:50–16:00. Trading day with settlement obligations; settles 9 Nov (M 2026211); 8 Nov stays a settlement holiday | 2026 | PRIMARY | NSE/CMTR/76941, NCL/CMPT/77037 | Own timetable (`SPECIAL_TIMETABLES`); MIS blocked (`MIS_CUTOFF_UNKNOWN`) until Zerodha's square-off time is loaded; excluded from the 246 regular sessions used for annualisation |
| Years outside 2026; the BSE calendar | Not loaded | — | UNKNOWN | — | Every check on those dates blocks (`SESSION_UNKNOWN`) |

Replay over history needs the historical holiday and settlement calendars loaded first. The engine refuses to guess them.

## 2. Session timetable (normal market, regular days)

| Window (IST) | Applies to | Orders accepted | Effective | Status | Source |
| --- | --- | --- | --- | --- | --- |
| 09:00–09:05 pre-open entry | All equity | Limit + market (no SL, IOC, DQ) | 7 Sep 2026 | PRIMARY | NSE/CMTR/74969, SEBI CAS circular |
| 09:05–09:08 pre-open | All equity | Limit only | 7 Sep 2026 | PRIMARY | same |
| 09:08–09:10 random close | All equity | Treated as **closed** (acceptance not guaranteed) | 7 Sep 2026 | ASSUMPTION | same |
| 09:00–09:07 / 09:07–09:08 | All equity | Old pre-open: entry, then random close | until 6 Sep 2026 | PRIMARY | NSE/CMTR/73927 §1.1 |
| 09:15–15:30 continuous | Stocks without derivatives | Limit, market, SL, SL-M | — | PRIMARY | NSE/CMTR/73927 §2.2 |
| 09:15–15:15 continuous | Stocks with derivatives (F&O) | Limit, market, SL, SL-M | 3 Aug 2026 | PRIMARY | SEBI CAS circular |
| 15:15–15:20 CAS transition | F&O stocks | None (Zerodha queues these as AMO; broker behaviour not modelled) | 3 Aug 2026 | PRIMARY | SEBI CAS circular, ZERODHA/CAS |
| 15:20–15:25 CAS entry | F&O stocks | Limit + market; no SL | 3 Aug 2026 | PRIMARY | SEBI CAS circular, NSE/CMTR/73362 |
| 15:25–15:28 CAS entry | F&O stocks | Limit only | 3 Aug 2026 | PRIMARY | same |
| 15:28–15:30 CAS random close; 15:30–15:35 matching | F&O stocks | None | 3 Aug 2026 | PRIMARY | same |
| 15:50–16:00 post-close | All | Market only, at the day's closing price; only stocks that traded that day | 3 Aug 2026 (15:40–16:00 before) | PRIMARY | SEBI CAS circular; NSE/CMTR/73927 §1.8 |

Other session rules:

- **CAS price band.** ±3% of the CAS reference price (the VWAP from 15:00 to 15:15, or the LTP, or the previous close). The engine intersects this with the day's band.
- **CAS order carry-over.** Unexecuted continuous-session limit orders carry into CAS. SL orders, icebergs and orders outside the CAS band do not.
- **Excluded sessions.** Special pre-open (IPO or relisting day), periodic call auctions for illiquid stocks, T+0 series and block windows are outside scope; the engine blocks them. Muhurat 2026 uses its own loaded table; any other special session without a table raises `RuleUnknown`.
- **Policy: no market orders in auctions.** Market orders are not allowed in pre-open or CAS (`POLICY_LIMIT_ONLY_IN_AUCTION`). There is no same-day LTP to base market protection on.

## 3. Series and groups (settlement type)

| Exchange | Code | Meaning | Intraday (MIS) | BTST | Fresh buy | Status | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NSE | EQ | Rolling settlement | Broker list decides | Allowed | Allowed | PRIMARY | NSE/CMTR/73927 §1.3 |
| NSE | BE | Trade-for-trade, no netting | **Not possible** | Blocked | Allowed | PRIMARY | §1.4; ZERODHA/RMS-XT |
| NSE | BZ | T2T, non-compliant companies | **Not possible** | Blocked | Allowed | PRIMARY | §1.4 |
| NSE | SM/ST/SZ, T0, BL | SME, T+0 beta, block window | — | — | Out of scope | ASSUMPTION | policy |
| BSE | A, B | Treated as normal rolling | Broker list decides | Allowed | Allowed | ASSUMPTION | BSE group definitions not read |
| BSE | T, XT | Trade-for-trade | Not possible | Blocked | Allowed | BROKER_OFFICIAL | ZERODHA/RMS-XT |
| BSE | X, Z | Zerodha blocks MIS; BTST blocked (conservative) | Blocked | Blocked | Allowed | SECONDARY | ZERODHA/BSE-GROUPS-SUMMARY |
| BSE | ZP, P | CDSL does not allow credit | Blocked | Blocked | **Blocked** | SECONDARY | same |
| BSE | M, MT, MS, TS, SS, ST | SME / institutional platform | — | — | Out of scope | ASSUMPTION | policy |

**Selling T2T shares.**

- Shares bought today cannot be sold today. This is BROKER_OFFICIAL from Zerodha's T2T article, and consistent with no-netting settlement.
- Shares bought yesterday that are not yet in demat are CONFLICTING. Zerodha's T2T article says they can be sold on T+1, but its RMS article says a sale before demat credit is rejected and BTST is blocked. The engine treats them as **not sellable** (`T2T_NEXT_DAY_SALE_UNVERIFIED`).
- A policy flag can relax this once it is verified against the account.

## 4. Surveillance frameworks

| Framework / stage | T2T | Max band | Margin | ASD (buyer deposit) | Trading days | Other | Zerodha | Status | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM I | — | 5% | 100% | — | All | — | MIS blocked | PRIMARY | NSE/SURV/71526 |
| GSM II | Yes | 5% | — | 50% | All | — | Fresh buys blocked; MIS blocked | PRIMARY / BROKER | NSE/SURV/71526, ZERODHA/GSM2 |
| GSM III | Yes | 5% | — | 100% | **First trading day of the week only** | — | Fresh buys blocked | PRIMARY / BROKER | same |
| GSM IV | Yes | 5% | — | 100% | First trading day of the week only | **No upward movement** (upper band = base price) | Fresh buys blocked | PRIMARY / BROKER | same |
| ESM I (m-cap < ₹1,000 cr, no derivatives) | Yes | 5% (2% if already 2%) | 100% from T+2 | — | All | — | MIS blocked (T2T) | PRIMARY | NSE ESM FAQ v1.1 |
| ESM II | Yes | 2% | 100% | — | All, **periodic call auction only** | — | — | PRIMARY | same |
| IBC 0 | Gross settlement | 5% | 100% from T+2 | — | All | — | MIS blocked | PRIMARY | NSE/SURV/75652 (from 10 Aug 2026) |
| IBC I | Gross | 2% | 100% | 100% | All | — | Fresh buys blocked | PRIMARY / BROKER | NSE/SURV/75652, ZERODHA/SURV-INDICATORS |
| IBC II | Gross | 2% | 100% | 100% | **Once a week** | — | Fresh buys blocked | PRIMARY / BROKER | same |
| LT-ASM I–III, ST-ASM I–II | — | — | Not read | — | All | Pledging not allowed | MIS blocked (assumption) | SECONDARY | NSE ASM circular mirrors, Zerodha ASM summary |
| LT-ASM IV | Yes | — | — | — | All | — | — | BROKER_OFFICIAL | ZERODHA/SURV-INDICATORS |
| Unsolicited SMS | — | — | — | — | All | — | MIS blocked | BROKER_OFFICIAL | ZERODHA/MIS-BLOCKS |
| Non-promoter holding < 25% | — | 10% | — | — | All | — | — | PRIMARY | NSE/CMTR/73927 §3.1F |

Engine rules for this section:

- **Combined stages.** Where a stock carries several flags, the most restrictive combination applies (`Restrictions.merge`).
- **Band conflict.** A supplied band wider than the surveillance maximum blocks as an inconsistent snapshot (`SURVEILLANCE_BAND_CONFLICT`).
- **Missing lists.** If the surveillance lists for the date were not loaded, the order blocks (`SURVEILLANCE_UNKNOWN`).
- **Selling stays possible.** Zerodha's fresh-buy blocks do not stop selling existing holdings, subject to once-a-week days and bands.

## 5. Prices

| Rule | Value | Effective | Status | Source |
| --- | --- | --- | --- | --- |
| Tick size (EQ, BE, BZ, T0 …; not ETFs) | <₹250: 0.01; ₹250–1,000: 0.05; >1,000–5,000: 0.10; >5,000–10,000: 0.50; >10,000–20,000: 1.00; >20,000: 5.00 | 15 Apr 2025 | PRIMARY | NSE/CMTR/67133, 73927 §3.3 |
| Tick reference price | Close on the last trading day of the previous month; reviewed monthly. Split/bonus keeps the old tick until the next review | — | PRIMARY | same |
| Earlier tick regime | <₹250: 0.01; ≥₹250: 0.05 | 10 Jun 2024 – 14 Apr 2025 | SECONDARY (start date) | NSE/CMTR/67133 + summary of 62174 |
| Static band (non-F&O stocks) | 2/5/10/20%, set by surveillance, on the base price | — | PRIMARY | §3.1 |
| Band rounding | Upper limit rounded **down**, lower limit **up**, to tick | — | ASSUMPTION | §3.1 says "aligned as per tick size" |
| F&O stocks | No static band. Dynamic operating range of 10%, flexed by 5%, then 3%, then 2% with cooling-off periods, sliding (not widening) | — | PRIMARY | §3.1C |
| Market price protection (exchange) | Market orders fill only within LTP ±3% (LTP > ₹50) or ±₹1.50 (LTP ≤ ₹50). Rejected if no trade today | — | PRIMARY | §3.6A |
| Algo market orders | NSE pre-emptively rejects true algo market orders in the normal market; allowed in post-close and (from 2026) CAS / pre-open | 7 Jul 2025 | PRIMARY | NSE/CMTR/68802, 73362 |
| SL-limit gap | Reject if \|limit − trigger\| > 3% of trigger (trigger > ₹50) or ₹1.50 (trigger ≤ ₹50) | — | PRIMARY | §3.6B |
| SL direction | Buy: trigger ≤ limit. Sell: trigger ≥ limit | — | ASSUMPTION | standard broker validation |
| Quantity alert | Orders above 25,000 shares raise an exchange alert (engine WARN) | — | PRIMARY | §3.2 |
| Per-security quantity freeze / order-value limit | In the daily security file | — | UNKNOWN (not loaded) | §3.2 |
| Market-wide circuit breaker | 10%: before 13:00 halt 45 min; 13:00–14:30 halt 15 min; after 14:30 no halt. 15%: before 13:00 1 h 45 min; 13:00–14:00 45 min; after 14:00 closed for the day. 20%: closed for the day. Resume via 15-min pre-open | — | PRIMARY | §3.7 |
| Daily close (non-CAS stocks) | VWAP of the last 30 minutes; else LTP; else the previous close | — | PRIMARY | §3.4 |
| Daily close (CAS stocks) | CAS equilibrium price; else the CAS reference price | 3 Aug 2026 | PRIMARY | NSE/CMTR/73362 §5 |

## 6. Selling, short selling and delivery risk

| Rule | Status | Source | Engine |
| --- | --- | --- | --- |
| Naked short selling is not permitted; every sale must be delivered at settlement. Retail may short intraday only | PRIMARY | NSE/CMTR/73927 §4.2 | CNC sell beyond holdings → `INSUFFICIENT_SELLABLE_QTY`. Intraday shorting disabled by policy |
| BTST (sell T1 shares before demat credit) allowed for rolling-settlement stocks | BROKER_OFFICIAL / SECONDARY | Zerodha | Allowed with `BTST_SHORT_DELIVERY_RISK` warning |
| BTST blocked on a settlement holiday | SECONDARY | Zerodha (summary) | `BTST_NOT_ALLOWED` |
| Short delivery leads to an auction on T+1 (~14:30, 30 min, ±20% band). Penalty 0.05% + GST (exchange shortage) or 1% facilitation fee + GST (internal shortage). Close-out at the higher of the highest price since the trade or 20% above the auction-day close. Zerodha blocks a 120% short-delivery margin | BROKER_OFFICIAL | ZERODHA/SHORT-DELIVERY | Documented; to be simulated in Phase 3 |
| Selling CNC shares bought the same day nets intraday and is charged intraday rates | ASSUMPTION | — | `INTRADAY_REVERSAL_OF_DELIVERY` warning |
| Proceeds from selling T1 holdings are not usable the same day; sale proceeds on a settlement holiday are delayed | SECONDARY | Zerodha (summary) | Phase 1 ledger must treat proceeds as unavailable until settlement |

## 7. Zerodha products

### MIS (intraday)

| Rule | Status | Source |
| --- | --- | --- |
| Auto square-off 15:12 for F&O (CAS) stocks and 15:25 for others, from 3 Aug 2026. New MIS orders rejected after cut-off | BROKER_OFFICIAL | ZERODHA/CAS |
| Cut-off before 3 Aug 2026 | UNKNOWN (sources show 15:20 and 15:25) | — |
| MIS blocked for T2T, GSM, unsolicited-SMS, low-liquidity, narrow-circuit and high-margin stocks, and during high volatility. Only CNC is then allowed | BROKER_OFFICIAL | ZERODHA/MIS-BLOCKS |
| Per-stock MIS eligibility and leverage come from the broker's list | UNKNOWN until loaded | — |
| Auto square-off by dealer: ₹50 + GST per order | BROKER_OFFICIAL | ZERODHA/CHARGES |

MIS is outside the engine's default policy (CNC only); the paper gate enables it only for the intraday sleeve, always fully funded. The engine still evaluates its rules when policy allows it.

### MTF

Out of scope. The user removed MTF on 4 Nov 2026. The previous MTF rules and their sources are kept in `archive/phase_0_1/docs/RULES_REGISTER.md` for reference only.

## 8. Charges (Zerodha snapshot, 4 Nov 2026)

| Component | Delivery (CNC) | Intraday (MIS) | Status |
| --- | --- | --- | --- |
| Brokerage | ₹0 | 0.03% or ₹20 per executed order, whichever is lower | BROKER_OFFICIAL |
| STT | 0.1% on buy and sell | 0.025% on sell | BROKER_OFFICIAL (rates); basis ASSUMPTION, below |
| Exchange transaction | NSE 0.00307%. BSE 0.00375% (A, B and others); **0.1% for X, XT, Z, ZP**; 1% for SS, ST; 0.00275% for M, MT, TS, MS | same | BROKER_OFFICIAL |
| SEBI fee | ₹10 per crore | same | BROKER_OFFICIAL |
| Stamp duty (buy side only) | 0.015% | 0.003% | BROKER_OFFICIAL |
| NSE IPFT | ₹0.01 per crore + GST | same | BROKER_OFFICIAL |
| GST | 18% of (brokerage + exchange transaction + SEBI fee + IPFT) | same | BROKER_OFFICIAL |
| DP charge | ₹15.34 incl. GST (male primary holder; ₹15.05 female) once per scrip per sell day, irrespective of quantity; posted to the **funds statement**, not the contract note | none | BROKER_OFFICIAL (ZERODHA/DP-CHARGES) |
| Debit-balance surcharge | +₹20 per executed order | | UNKNOWN |

**STT basis (ASSUMPTION until reconciled with a real contract note).** STT is computed per exchange, ISIN, trade date, trade kind and side: aggregate value ÷ quantity rounded to the paisa, STT on that, rounded to the nearest rupee (50 paise and above up). Zerodha documents the rupee rounding (ZERODHA/STT-ROUNDING) and its three worked examples (₹53, ₹50, ₹13) are reproduced in tests; the aggregation level comes from the 2004 draft STT rules (STT-RULES-2004-DRAFT, third-party copy); NSE/INSP/45900 shows contract-note STT is an integer field. Implemented in `rules.charges.day_charges`; a single-order estimate (`costs.charges`) treats the order as the only fill of its scrip-day.

**Other rounding (ASSUMPTION).** Brokerage, exchange, SEBI, IPFT and GST per executed order, rounded to the paisa half-up, GST on the unrounded base. **Stamp-duty allocation is UNRESOLVED** (per-order paisa assumed). DP is reconciled against the funds statement (`reconcile_dp`), never inferred from contract notes. Break-even percentages computed before 5 Nov 2026 used per-order paisa STT and remain estimates.

The schedule has no published effective dates. Using it for past dates sets `counterfactual=True`.

Worked examples tested in `tests/test_charges_broker.py`:

- **NSE delivery buy, ₹10,000:** STT 10.00, exchange 0.31, SEBI 0.01, stamp 1.50, GST 0.06. Total **₹11.88**.
- **NSE intraday ₹50,000 round trip:** buy ₹21.08, sell ₹32.08.
- **BSE X-group delivery sell, ₹20,000:** ₹43.62, versus ₹20.91 for an A-group stock.

## 9. Kite Connect API and retail-algo rules

| Rule | Status | Source |
| --- | --- | --- |
| Static IP required for API order placement (max 2 IPs, 1 change per calendar week). Data, orderbook and positions endpoints work from any IP | CONFLICTING start date: 1 Apr 2026 (static-IP article) vs 1 Apr 2025 (FAQ). In force either way | ZERODHA/STATIC-IP, ZERODHA/KITE-API-FAQ |
| API MARKET and SL-M orders must carry `market_protection` (−1 = auto, or a percentage between 0 (exclusive) and 100). 0 or missing is rejected. Kite converts them to protected limits | BROKER_OFFICIAL | ZERODHA/KITE-API-FAQ, KITE/ORDERS |
| Policy: explicit protection ≤ 5%; the "auto" band is undocumented | ASSUMPTION | policy |
| 10 orders/second per client account (HTTP 429; invalid requests count), 400/minute, 5,000/day, 25 modifications per order | BROKER_OFFICIAL | KITE/LIMITS, ZERODHA/KITE-API-FAQ |
| Self-built algos under 10 orders/second need no exchange registration. Orders carry an exchange algo ID (generic below the threshold) | BROKER_OFFICIAL (threshold) / SECONDARY (algo-ID detail) | ZERODHA/KITE-API-FAQ, SEBI retail-algo summary |
| Access token valid for the trading day; it expires the next morning before market open, or when a new session is generated. Daily login required. No stored TOTP or cookie automation | BROKER_OFFICIAL | ZERODHA/KITE-API-FAQ |
| Order tag: up to 20 alphanumeric characters. Iceberg: 2–50 legs. Validity: DAY, IOC, TTL | BROKER_OFFICIAL | KITE/ORDERS |
| Personal API is free, without live or historical data. Connect costs ₹500/month and includes WebSocket data and historical candles | BROKER_OFFICIAL | ZERODHA/KITE-API-FAQ |

## 10. Open items (unknown, conflicting or account-specific)

1. **Unloaded calendars.** BSE 2026 and all 2027 holiday and settlement calendars; historical calendars for replay. (Muhurat 8 Nov 2026 loaded on 5 Nov 2026.) Zerodha's MIS square-off time for Muhurat.
2. **15 Jan 2026 holiday.** Read the NSE original; currently seen only through a mirror's circular title.
3. **T2T next-day sale before demat credit.** Zerodha articles conflict. Verify on the account.
4. **ASM stage margins.** Read the NSE ASM framework annexure itself; we have only mirror summaries.
5. **BSE group definitions** (A, B, X, Z, ZP, P) and BSE price-band and tick rules. Read BSE's own notices.
6. **MIS cut-off before 3 Aug 2026** (15:20 or 15:25), needed for any intraday replay.
7. *(MTF interest items: no longer applicable; MTF removed.)*
8. **Contract-note reconciliation** of the STT aggregation basis, stamp-duty allocation and GST rounding against one real contract note; DP against the funds statement (DP basis itself is now BROKER_OFFICIAL: once per scrip per sell day).
9. **Debit-balance ₹20 surcharge** (applies if the account goes into a debit balance).
10. **Static IP start date conflict** (2025 vs 2026). Moot today, but recorded.
11. **Kite's "auto" protection band** (−1). Undocumented, so our policy forbids it.
12. **CAS edge cases.** Zerodha AMO queueing in 15:15–15:20, and CAS behaviour on special-session days.
13. **Illiquid-stock definition.** Zerodha's surveillance page describes the periodic-call-auction criteria differently (under 50 trades/day, under 10,000 shares) from NSE's consolidated circular (turnover under ₹2 lakh). Out of scope while call-auction stocks are blocked.
14. **Daily inputs.** Security-file tick sizes, quantity freezes and order-value limits. These are daily exchange files that the data phase must ingest.
15. **eDIS / DDPI for CNC sells via API.** If DDPI is absent, CDSL authorisation may be needed. Account-specific.

## 11. Source documents read

Primary: NSE/CMTR/73927 (consolidated, 28 Apr 2026), NSE/CMTR/67133, NSE/SURV/71526, NSE ESM FAQ v1.1, NSE/SURV/75652, NSE/CMTR/68802, SEBI CAS circular (16 Jan 2026, via NSE/CMTR/72394), NSE/CMTR/73362, NSE/CMTR/74969, NCL/CMPT/71904, NSE/CMTR/76941 (Muhurat 2026), NCL/CMPT/77037 (Muhurat settlement), NSE/INSP/45900 (contract-note fields).

Broker official: Zerodha STT and DP articles, Kite corporate-action adjustment article and forum answer (5 Nov 2026), Kite exceptions page, Zerodha charges, MTF FAQ, MTF funds statement entries, CAS article, MIS-blocks article, surveillance-indicators article, GSM stage-2 article, T2T article, RMS XT article, short-delivery article, static-IP article, Kite API FAQ, Kite orders docs, Kite rate-limit docs.

The full registry, with URLs and check dates, is in `src/marketlab/rules/provenance.py`. Downloaded originals were used only as read-only reference and are not stored in the repository.
