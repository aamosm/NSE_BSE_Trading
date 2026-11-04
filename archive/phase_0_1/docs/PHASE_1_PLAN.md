# Phase 1 plan: cash and MTF accounting

**Status (4 Nov 2026):** implemented in `src/marketlab/ledger/` at the user's direction, before the external GPT review of Phase 0. That review should cover this plan and the code together. Fixtures A–H pass with the exact values below (`tests/test_ledger_fixtures.py`). A mutation check deliberately broke 8 ledger rules and the tests caught all 8, after fixtures G and H and the DP/available-cash tests were added. The first run caught only 4.

Scope: Phase 1 in `prompts/PHASE_PROMPTS.md`, which covers a balanced ledger, cash and MTF lots, funding liability, accrued interest, pledge lifecycle, margin headroom, partial exits, conversion to cash, forced exits and a corporate action. Hand-worked fixtures and a replayable accounting demonstration are required. There is no broker connection and no fill simulation: fills are given as inputs (fill simulation is Phase 3).

## 1. Interfaces

```
ledger/journal.py   Posting(account, amount)            signed: debit +, credit −, paisa-exact
                    JournalEntry(id, at, kind, memo, postings, refs)   must sum to 0
                    Journal: append-only; balance(account), balances(prefix), trial_balance()
ledger/book.py      Book(calendar, schedule, interest_convention)
                      deposit / withdraw
                      buy(fill) / sell(fill)            fill = (fill_id, at, exchange, isin, product, qty, price, …)
                      convert_mtf_to_cnc(at, isin, qty)
                      split(ex_date, isin, new, old) / cash_dividend(pay_date, isin, per_share)
                      advance_to(day, marks, margin_pct)  settles, accrues interest, checks MTF margin
                      reports: cash_available, nlv, positions, mtf_status, round_trips, statement
ledger/replay.py    run(events) -> Book                  pure, deterministic; duplicate event IDs ignored
```

Every buy and sell in a replay first passes through `rules.engine.evaluate_order`. A rejected order is recorded as a decision with its reason codes and changes nothing in the ledger.

## 2. Chart of accounts

| Account | Type | Meaning |
| --- | --- | --- |
| `asset:cash` | Asset | Settled cash at the broker (EQ ledger) |
| `asset:settlement:<date>` | Asset (signed) | Net obligation for one settlement date: positive = receivable, negative = payable. Mirrors Zerodha's "Net Settlement for Equity" |
| `asset:holdings:<CNC|MTF>:<isin>` | Asset | Open lots at cost (trade value, excluding charges) |
| `asset:mtf_margin_blocked` | Asset | Client cash blocked for MTF MTM loss or additional maintenance margin |
| `liability:mtf_funded:<isin>` | Liability | Broker-funded principal |
| `liability:mtf_interest_accrued` | Liability | Interest accrued, not yet debited |
| `equity:contributions` / `equity:withdrawals` | Equity | External flows (never returns) |
| `income:realized:<CNC|MTF>` | Income | Sale value − FIFO cost (gross) |
| `income:dividends` | Income | Cash dividends |
| `expense:<component>` | Expense | brokerage, stt, exchange_txn, sebi, ipft, stamp, gst, dp, pledge, unpledge, square_off |
| `expense:mtf_interest` | Expense | MTF interest |

Valuation marks are **not** journal entries. Unrealised P&L is computed from open lots and marks.

## 3. Accounting rules

1. **Trade date posting.**
   - The trade and its contract-note charges post on the trade date into `asset:settlement:<T+1>`. `T+1` comes from `MarketCalendar.settlement_date`, which skips settlement holidays.
   - Cash moves when that settlement date arrives.
2. **Charges are expensed per order.**
   - DP is charged once per (ISIN, sell date) for CNC and MTF sells.
   - The MTF pledge fee is charged once per (ISIN, buy date). The unpledge fee is charged once per (ISIN, sell or convert date).
   - The square-off fee applies once per broker-forced order.
   - Each fee carries 18% GST.
   - Fees settle with the trade they belong to.
   - These are ASSUMPTIONS on timing, to be reconciled with contract notes.
3. **Lots and matching.**
   - Each buy fill creates a lot.
   - Sells match FIFO within (ISIN, product).
   - CNC sells require settled quantity. BTST is handled by the rules engine, not the ledger.
4. **MTF buy.**
   - Initial margin = margin% × trade value, rounded to the paisa half-up. Margin% is VaR + 5×ELM, or VaR + 3×ELM for F&O stocks.
   - Funded principal = trade value − initial margin. This is Zerodha's FAQ definition.
   - Posting: Dr holdings (value) / Cr settlement (initial margin + charges) / Cr `liability:mtf_funded`.
5. **MTF sell.**
   - Funded principal is repaid pro-rata to the matched lots' quantity. This is inferred from the "buy value is reversed upon selling" ledger description, so it is an ASSUMPTION.
   - The rest of the proceeds goes to the settlement account.
   - Margin blocked for this ISIN is released to cash once no MTF quantity remains.
6. **Conversion MTF → CNC.** The client pays the lots' **original** funded amount from available cash (Zerodha FAQ), then the lot changes product. The unpledge fee is charged.
7. **Splits and bonus issues.** Quantity × new/old, cost unchanged, original lot dates kept. Funded principal is unchanged. A bonus issue is treated like a split for performance accounting. The tax treatment of bonus shares (zero-cost lots on the allotment date) is out of scope until tax reporting.
8. **Rounding.** Charges follow `rules/charges.py`. Interest accrues unrounded per day and is rounded to the paisa when posted (ASSUMPTION).

## 4. MTF interest, margin and forced exit

- **Rate:** 0.04% per day on the funded amount. **From T+1 until the stocks are sold** (Zerodha FAQ).
- **Sale day:** the FAQ says BTST interest is charged "on the opening balance on T+1". So a stock bought on T and sold on T+1 pays one day, and **the sale day counts**. The first day is the buy's settlement date.
- **Weekends and holidays are still UNKNOWN.** Both conventions are implemented and the fixtures report both:
  - `CALENDAR_DAYS` is the default and the conservative choice. It charges every calendar day from settlement(T) through the sale date.
  - `TRADING_DAYS` charges only regular trading days in that range.
- **Debit timing is UNKNOWN.** Zerodha says interest is debited "on specific dates". We accrue a liability and debit it when an MTF position fully closes and at month end. This is an ASSUMPTION.
- **Margin requirement** = margin% (current) × open buy value + MTM loss (buy value − market value, when positive).
  - Zerodha collects MTM daily on losing positions, based on the buy price.
  - The additional requirement above what has been collected is blocked from free cash.
  - Whatever free cash cannot cover is a **shortfall**, and the position enters `MARGIN_SHORTFALL`.
  - The broker *may* square off the position but is not obliged to.
- **Forced exit:** the sale is posted like a normal MTF sell plus a ₹50 + GST square-off fee per order. The lot is marked `BROKER_LIQUIDATED`.

## 5. Hand-worked fixtures

All fixtures use NSE and the Zerodha schedule observed 2026-11-04, so they are not counterfactual. Arithmetic is shown so a reviewer can redo it.

- 2026-11-07 and 11-08 are a weekend; 11-08 is also the Muhurat special session, which is not a regular trading day.
- 2026-11-10 is a trading and settlement holiday.

Charge abbreviations: STT 0.1% (delivery/MTF); txn 0.00307%; SEBI ₹10/crore; stamp 0.015% on buys; GST 18% on (brokerage + txn + SEBI + IPFT).

### A. Normal cash trade

| Step | Arithmetic | Result |
| --- | --- | --- |
| Deposit 4 Nov | — | cash 10,000.00 |
| Buy 10 × 500.00 on Wed 4 Nov (settles Thu 5 Nov) | STT 5.00; txn 0.1535→0.15; SEBI 0.005→0.01; stamp 0.75; GST 0.18×0.158505=0.0285→0.03 | charges **5.94**; cash after settlement 4,994.06 |
| Sell 10 × 520.00 on Mon 9 Nov (settles **Wed 11 Nov**, because 10 Nov is a holiday) | STT 5.20; txn 0.15964→0.16; SEBI 0.0052→0.01; GST 0.18×0.1648452=0.0297→0.03; DP 15.34 | sell charges **5.40** + DP **15.34** |
| Result | gross 200.00 − (5.94 + 5.40 + 15.34) | realised net **173.32**; final cash **10,173.32**; still pending on 10 Nov |

### B. MTF across a weekend and a holiday

| Step | Arithmetic | Result |
| --- | --- | --- |
| Deposit 4 Nov | — | 10,000.00 |
| MTF buy 20 × 400.00 on Thu 5 Nov, margin 25% (VaR 10 + 5×ELM 3) | value 8,000; initial margin 2,000.00; funded **6,000.00**. Brokerage min(24, 20)=20; STT 8.00; txn 0.2456→0.25; SEBI 0.008→0.01; stamp 1.20; GST 0.18×20.253608=3.6456→3.65; pledge 15+2.70 | charges **33.11**; pledge **17.70**; cash on 6 Nov = 10,000 − 2,000 − 33.11 − 17.70 = **7,949.19** |
| Interest | 6,000 × 0.04% = 2.40/day from 6 Nov | |
| MTF sell 20 × 410.00 on Wed 11 Nov | brokerage 20; STT 8.20; txn 0.25174→0.25; SEBI 0.0082→0.01; GST 0.18×20.2599482=3.6468→3.65; DP 15.34; unpledge 17.70 | sell charges **32.11** |
| Interest days | Calendar: 6, 7, 8, 9, 10, 11 Nov = 6 → **14.40**. Trading days: 6, 9, 11 Nov = 3 → **7.20** | difference **7.20**: the unknown day-count matters |
| Result (calendar) | 200.00 − 33.11 − 17.70 − 32.11 − 15.34 − 17.70 − 14.40 | net **69.64**; final cash **10,069.64** after 12 Nov settlement and interest debit |
| Result (trading days) | same costs, interest 7.20 | net **76.84** |

### C. Several lots and a partial exit (CNC, FIFO)

| Step | Arithmetic | Result |
| --- | --- | --- |
| Buy 10 × 100.00, Wed 4 Nov | STT 1.00; txn 0.0307→0.03; SEBI 0.001→0.00; stamp 0.15; GST 0.0057→0.01 | **1.19** |
| Buy 10 × 110.00, Thu 5 Nov | STT 1.10; txn 0.03377→0.03; SEBI 0.0011→0.00; stamp 0.165→**0.17** (half-up); GST 0.0063→0.01 | **1.31** |
| Sell 15 × 120.00, Mon 9 Nov | STT 1.80; txn 0.05526→0.06; SEBI 0.0018→0.00; GST 0.0103→0.01; DP 15.34 | **1.87** + 15.34 |
| FIFO | 10 from lot 1 (cost 1,000) + 5 from lot 2 (cost 550) = 1,550; proceeds 1,800 | realised gross **250.00**; open 5 @ 110.00 (cost **550.00**) |
| Cash after 11 Nov | 10,000 − 1,001.19 − 1,101.31 + 1,800 − 1.87 − 15.34 | **9,680.29** |
| P&L identity at mark 120 | 250 + (600 − 550) − 19.71 | 280.29 = NLV 10,280.29 − 10,000 |

### D. MTF margin change (sufficient cash, and a shortfall)

| Step | Arithmetic | Result |
| --- | --- | --- |
| As B: MTF buy 20 × 400 on 5 Nov, margin 25% | initial margin 2,000 collected | |
| Fri 6 Nov close: margin rises to 40%, mark 380 | requirement 0.40×8,000 + (8,000 − 7,600) = 3,200 + 400 = 3,600; collected 2,000 | call **1,600.00** |
| D1: deposit 10,000 | free cash 7,949.19 ≥ 1,600 | 1,600 blocked; free cash **6,349.19**; status OK |
| D2: deposit 2,100 | free cash 2,100 − 2,000 − 33.11 − 17.70 = 49.19 | 49.19 blocked; shortfall **1,550.81**; status `MARGIN_SHORTFALL` |

### E. Forced exit after the D2 shortfall

| Step | Arithmetic | Result |
| --- | --- | --- |
| Broker squares off 20 × 370.00 on Mon 9 Nov | brokerage 20; STT 7.40; txn 0.22718→0.23; SEBI 0.0074→0.01; GST 0.18×20.2345874=3.6422→3.64; square-off 50 + 9.00; DP 15.34; unpledge 17.70 | sell charges **31.28**; fees **59.00 + 15.34 + 17.70** |
| Interest | Calendar 6–9 Nov = 4 days → **9.60** (trading days 6, 9 Nov → 4.80) | |
| Realised | 7,400 − 8,000 | gross **−600.00** |
| Final cash (calendar) | 2,100 − 600 − 33.11 − 17.70 − 31.28 − 59.00 − 15.34 − 17.70 − 9.60 | **1,316.27** after the 11 Nov settlement |

### F. Corporate action (1:2 split), economically equal to A

| Step | Result |
| --- | --- |
| Buy 10 × 500.00 on 4 Nov (charges 5.94) | lot 10 @ 500, cost 5,000 |
| Split new 2 : old 1, ex-date Mon 9 Nov | lot 20 @ 250, cost **5,000.00**, lot date 4 Nov kept |
| Sell 20 × 260.00 on Wed 11 Nov (turnover 5,200: charges 5.40 + DP 15.34) | gross **200.00**; net **173.32**, the same as fixture A |

### G. Friday MTF buy: interest starts at Monday settlement

Buy 20 × 400.00 MTF on Fri 6 Nov (settles Mon 9 Nov), sell Wed 11 Nov. Calendar days 9, 10, 11 = 3 × 2.40 = **7.20**. Counting from the trade date would add Sat/Sun and give 12.00.

### H. Partial MTF exit

| Step | Arithmetic | Result |
| --- | --- | --- |
| MTF buy 20 × 400.00 on 5 Nov, 25% margin | funded 6,000 | |
| Sell 5 × 410.00 on Mon 9 Nov | funded repaid 6,000 × 5/20 = **1,500**. Brokerage 0.3% × 2,050 = 6.15 (under the cap); STT 2.05; txn 0.062935→0.06; SEBI 0.00205→0.00; GST 0.18×6.214987=1.1187→1.12 | sell charges **9.38**; DP 15.34; unpledge 17.70; realised gross **50.00** |
| Remaining lot | 15 shares, cost 6,000.00, funded **4,500.00**, initial margin 1,500.00 | `PARTIALLY_CLOSED` |
| Interest to 11 Nov | 6–9 Nov on 6,000 (4 × 2.40) + 10–11 Nov on 4,500 (2 × 1.80) | **13.20** |

## 6. Invariants (property tests)

1. Every journal entry sums to zero, and the trial balance is zero after any event sequence.
2. Lot quantities equal net filled quantity per (ISIN, product); no lot quantity is negative.
3. `holdings` account balance = Σ open lot cost.
4. `liability:mtf_funded` = Σ open MTF lots' remaining funded principal.
5. P&L identity: NLV − net contributions = realised gross + unrealised + dividends − expensed charges − interest.
6. Replaying the same events gives an identical ledger. Feeding a fill ID twice changes nothing.
7. Cash never goes negative except through a recorded MTF shortfall or an explicit debit balance.

## 7. Acceptance criteria

- Fixtures A–H reproduce the exact rupee values above.
- The invariants hold under randomised event sequences (Hypothesis).
- A replay demo (`python -m marketlab.ledger.demo`) prints, for a synthetic cash + MTF scenario:
  - rule decisions, including one rejected order with its reasons and no ledger effect;
  - the journal and trial balance;
  - positions, MTF status and P&L;
  - metrics from `docs/METRICS.md`.
- The handoff lists every remaining ASSUMPTION/UNKNOWN: interest day-count and debit dates, charge rounding, fee timing and repayment ordering.
