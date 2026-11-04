# NSE/BSE Trading — independent Phase 0 and Phase 1 review

**Verdict: NOT READY for Phase 2 sign-off.** The existing accounting foundation is worth continuing, but input validation, spending controls and several financial outputs need correction before historical results can be trusted.

Reviewed on 4 November 2026. Repository: [aamosm/NSE_BSE_Trading](https://github.com/aamosm/NSE_BSE_Trading). Pinned commit: **19d12dcac7415b17d3a5192035517ad285f9b389**. The remote main reference still pointed to this commit at the end of the review.

This is a review, not an implementation change. Production code was not edited; no commits, issues, comments or pull requests were posted. Claude remains the implementation owner under AGENTS.md.

## What was actually verified

| Check | Observed result |
| --- | --- |
| Repository files | 58 relevant files downloaded at the pinned commit; bytes verified against Git blob hashes |
| Environment | Linux, Python 3.12.14, separate virtual environment, repository's exact requirements-dev.lock |
| Original test suite | **211 passed**, none failed or skipped |
| Rules demo | Completed successfully |
| Ledger demo | Completed; 5 orders applied and 3 rejected; duplicate ignored; saved-log replay identical |
| Ledger demo accounting | Settled cash ₹9,031.52; trial balance and P&L identity gap both ₹0.00 |
| Independent regressions | **10 tests executed, 10 failed**, one for each finding below |
| Broker activity | None; synthetic fixtures only |

The independent tests assert required behavior and are intentionally red on this commit. They do not mean that the original 211 tests failed. They are included as test_review_regressions.py, with actual pytest output in regression_results.txt. These were run outside the downloaded source tree with its src directory on PYTHONPATH.

Scope included the project contract and handoff, rules, metrics, ledger, tests, cost assumptions and reference-review claims. The two large planned experiment registries and the original build-guide file were not needed for this review. I did not run the 1,200-scenario or 1,000-strategy campaigns, connect Zerodha, reproduce the reported mutation campaign, or execute the 20 reference bots.

Severity: **P1** means a required input or financial admission control can be bypassed; **P2** means a reproducible accounting, calendar or statistical error. These findings apply to the simulation. They are not claims that any real order was placed.

## Confirmed findings

### R01 — P1: replay replaces a stale snapshot's date

**Location:** [ledger/replay.py, snapshot_from, lines 72–81 and _order, lines 152–154](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/replay.py#L72). The rules engine's date check is at [rules/engine.py, lines 91–93](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/engine.py#L91).

**Trigger:** submit an otherwise valid 4 November order with an instrument snapshot explicitly dated 3 November.

**Expected:** reject with STALE_SNAPSHOT. **Actual:** APPLIED with no warning. snapshot_from overwrites the supplied as_of with the order date, defeating the existing engine check.

**Smallest correction:** parse and preserve the source date; reject missing or stale required dates. Make fixture generation explicitly supply its intended date instead of making ingestion silently invent freshness. Later timestamp-level freshness remains Phase 2 work.

**Reproduction:** test_r01_replay_preserves_and_rejects_stale_snapshot_date.

### R02 — P1: omitted security-status fields silently mean safe

**Location:** [rules/types.py, InstrumentSnapshot, lines 82–85](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/types.py#L82); [rules/engine.py, lines 114–127](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/engine.py#L114).

**Trigger:** omit surveillance, suspended, special_preopen_today and in_periodic_call_auction from an otherwise valid input.

**Expected:** unknown required status blocks the new entry. **Actual:** APPLIED. Dataclass defaults supply an empty surveillance set and false flags. Explicit None is handled conservatively, but omission bypasses that protection.

**Smallest correction:** require explicit values or default to None. Update synthetic fixtures to state their known-safe values. Keep the unknown-status rejection tests.

**Reproduction:** test_r02_missing_security_status_is_unknown_not_safe.

### R03 — P1: netting makes unsettled MTF sale proceeds spendable

**Location:** [ledger/book.py, available_cash, lines 558–561](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L558), together with buy/sell postings to the same settlement-date account; [ledger/replay.py, funds check, lines 180–184](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/replay.py#L180).

**Trigger:** deposit ₹2,500; buy 20 MTF shares at ₹400 on 5 November with 25% initial margin; sell them on 9 November. Settled cash is ₹449.19. Place two further CNC purchases of ₹400 each that day.

**Expected:** the first purchase reserves ₹400.48 including the modeled fees, leaving ₹48.71; the second is rejected. **Actual:** both purchases are APPLIED. Reported available cash remains ₹449.19 because their payables are absorbed by the positive unsettled receipt in a net account.

This violates the documented conservative cash policy. Zerodha also explicitly states that MTF sale proceeds are usable only after T+1 settlement [S1].

**Smallest correction:** retain gross purchase obligations and receipt eligibility in the buying-power calculation, even if settlement journals are netted. Test several consecutive purchases, mixed products, holidays, partial exits and the transition to settlement.

**Reproduction:** test_r03_mtf_sale_receipt_cannot_fund_second_same_day_purchase.

### R04 — P1: a known margin shortfall does not stop a new purchase

**Location:** [ledger/book.py, _apply_margin, lines 509–536](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L509); [ledger/replay.py, _order, lines 164–184](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/replay.py#L164).

**Trigger:** deposit ₹2,100 and open an ₹8,000 MTF position. A price fall and margin increase produce a ₹1,550.81 shortfall. Deposit another ₹500 and request a ₹400 CNC purchase.

**Expected:** the new money remains committed to the unresolved margin requirement; the new entry is blocked. **Actual:** APPLIED while the book still records the larger shortfall.

**Smallest correction:** recalculate or reserve outstanding requirements when cash changes, and make order admission consult account-wide margin state. Block risk-increasing entries on unresolved shortfall or unknown required margin; preserve appropriate exits and reconciliation. This is a Phase 1 admission safeguard, not a request to build the full future allocator.

**Reproduction:** test_r04_unresolved_margin_shortfall_blocks_new_entry_after_deposit.

### R05 — P2: unpledging multiple purchase days is undercharged

**Location:** [ledger/book.py, sell, lines 359–362](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L359); related conversion logic at lines 458–460 and exit estimation around lines 600–601.

**Trigger:** buy the same ISIN using MTF on two different days and sell both lots together.

**Expected:** ₹30 unpledge expense before GST for those two purchase days. **Actual:** ₹15, omitting ₹17.70 including GST. The implementation deduplicates by ISIN and sell date. Zerodha's detailed FAQ instead explains unpledge charging by ISIN and original purchase day [S1].

**Smallest correction:** derive the applicable charge groups from the matched original lots. Apply the same grouping to actual sales, conversion affordability, conversion charges and exit estimates. Confirm partial-unpledge behavior separately rather than inventing a lifetime deduplication rule.

**Reproduction:** test_r05_mtf_unpledge_fee_counts_distinct_purchase_days.

### R06 — P2: same-day CNC round trips are accepted with delivery costs

**Location:** [ledger/book.py, _kind, lines 257–262](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L257), DP charging at lines 355–358; [rules/engine.py, lines 284–298](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/engine.py#L284).

**Trigger:** buy two CNC shares at ₹500 and sell those two shares at ₹500 later the same day.

**Expected:** either explicitly reject this unsupported Phase 1 accounting case, or account for its intraday classification. Zerodha confirms that a same-day CNC round trip incurs intraday charges [S3].

**Actual:** APPLIED with ₹0 brokerage, ₹15.34 DP and delivery STT. Under the project's fee schedule and paise-level model, the intraday round trip would have ₹0.60 brokerage and no DP charge.

**Smallest correction:** an explicit unsupported-case rejection is sufficient for this phase. Full support must classify matched intraday quantities and remaining delivery quantities correctly, including existing holdings and partial sales. Do not change every CNC order to intraday.

**Reproduction:** test_r06_same_day_cnc_round_trip_is_blocked_or_charged_as_intraday. Its STT check follows the existing simulator's rounding convention; contract-note rounding remains a separate reconciliation question.

### R07 — P2: a rejected split leaves earlier lots changed

**Location:** [ledger/book.py, split, lines 464–478](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L464).

**Trigger:** two lots contain two and three shares. Apply a 1-for-2 reverse split.

**Expected:** the unsupported fractional entitlement raises an error without partially changing holdings. **Actual:** the first lot becomes one share before validation fails on the second; quantities remain [1, 3] after the exception.

**Smallest correction:** validate and plan every affected lot before changing any of them. Add exception-path invariants. The current fractional test uses one lot; the generated tests use an always-integral 2-for-1 split, so neither catches this path.

**Reproduction:** test_r07_rejected_fractional_split_does_not_mutate_earlier_lots.

### R08 — P2: conversion fees disappear from closed-trade P&L

**Location:** [ledger/book.py, convert_mtf_to_cnc, lines 439–460](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/ledger/book.py#L439).

**Trigger:** buy 20 MTF shares at ₹400 on 5 November, convert all to CNC on 9 November, sell them at ₹400 on 11 November, and settle.

**Expected:** with no remaining positions, attributed net trade P&L reconciles to the account's loss after all costs. **Actual:** closed-trade P&L is −₹84.06 while account P&L is −₹101.76. The ₹17.70 conversion unpledge fee is recorded as an account expense but is not attributed to the converted lot.

**Smallest correction:** allocate conversion costs to the affected lots and preserve that attribution through partial conversion and later exits. Test reconciliation of closed-trade costs plus remaining-lot costs to attributable account expenses. A balanced double-entry journal does not prove this separate attribution is correct.

**Reproduction:** test_r08_conversion_fee_is_in_closed_trade_pnl.

### R09 — P2: tied out-of-sample outcomes receive an optimistic PBO rank

**Location:** [metrics/selection.py, lines 119–127](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/metrics/selection.py#L119).

**Trigger:** use two blocks and three trial columns: two rows [0.03, 0.02, 0.01], followed by two rows [0.01, 0.01, 0.01], scored by mean return.

**Expected under the stated “at or below the out-of-sample median” definition:** PBO 0.5. One split has all out-of-sample results tied at the median; the reverse split places the selected first trial above the median.

**Actual:** PBO 0.0. Counting all results less than or equal to the winner assigns the highest rank to a tie, making that split appear favorable.

**Smallest correction:** specify and implement a consistent tie policy, such as midranks, and handle duplicate or degenerate trial sets explicitly. Keep this tiny numerical example as a semantic test. It does not establish that a two-block estimate has useful statistical confidence.

**Reproduction:** test_r09_pbo_tied_oos_winners_are_not_ranked_above_median.

### R10 — P2: the 2026 Budget Sunday trading session is absent

**Location:** [rules/calendar.py, special-session data around line 51 and is_trading_day around line 89](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/calendar.py#L51); [rules/sessions.py, special-session handling, lines 149–150](https://github.com/aamosm/NSE_BSE_Trading/blob/19d12dcac7415b17d3a5192035517ad285f9b389/src/marketlab/rules/sessions.py#L149).

**Trigger:** query NSE for 1 February 2026.

**Expected:** identify the announced live Budget Sunday session. **Actual:** both regular-trading-day and special-session predicates return false. The NSE capital-market clearing circular explicitly confirms this trading date [S4].

**Smallest correction:** add an effective-dated session record and the verified trading/settlement schedule. Merely putting it in the special set will still leave session_at rejecting it as an unloaded timetable; distinguish known special trading from closed dates and unsupported execution. The supplied test checks discovery only, so add a proper session/settlement test for the chosen support level.

The documentation calls 245 the number of regular sessions excluding specials. That arithmetic is not the defect. Treating it as an exhaustive market-year calendar or universal annualization input would be incorrect.

**Reproduction:** test_r10_budget_sunday_is_a_known_session.

## What the review does not dispute

- The original 211-test claim was independently reproduced.
- Rejected orders do have audit records and rejection reasons. Their lack of journal postings is appropriate; “no trace in the books” does not mean the audit trail is absent.
- Saved-event replay is deterministic in the tested fixture. Broker submission durability, partial fills and crash recovery are later-phase work, not evidence established by this demo.
- The break-even table has explicit assumptions in METRICS.md: share price, quantities, margin, borrowing and charged days. The numbers are conditional examples, not portfolio return forecasts.
- Calendar-day MTF interest is already the default in Book. Zerodha's calculator explicitly includes weekends and public holidays [S2], so the handoff's blanket “unknown” statement should be corrected. Exact first-accrual interpretation around a Friday purchase, ledger debit timing and rounding still warrant statement reconciliation.
- Unknown future calendars and intentionally unsupported products may fail closed. Supporting every future phase is not a condition of this review.

## Documentation and evidence corrections

1. Update the interest provenance and HANDOFF.md using the primary calculator source. A trading-days-only convention can remain a clearly labeled sensitivity scenario, not an equally supported brokerage rule.
2. tests/test_ledger_replay.py uses max_examples=150 with the interest convention sampled as an input. That is not a guaranteed 150 distinct programs for each of two conventions. Correct the “150 × 2” claim or parameterize and execute the intended coverage.
3. The eight-mutation campaign is reported in the handoff, but no executable campaign evidence was reproduced in this review. Retain the mutation definitions, commands and results if continuing to use that count as evidence.
4. Refresh “specification kit only” and “local/no remote” descriptions where they no longer describe the project.
5. Before historical dividend use, make entitlement date and payment date explicit in the event contract. This is a follow-up design question, not one of the ten reproduced defects.

## Reference-bot claims: limited spot-check

REFERENCE_REVIEW.md names pinned revisions and generally describes limitations for this project's intended use. I checked two cited source paths, not all 20 repositories.

- [QuantConnect Lean ZerodhaFeeModel.cs at 9ecfed9](https://github.com/QuantConnect/Lean/blob/9ecfed9/Common/Orders/Fees/ZerodhaFeeModel.cs): the visible brokerage, STT and stamp constants support concern about applying that model to delivery. The inherited fee model was not fully audited in this spot-check, so this does not independently certify every detailed tax claim in the handoff.
- [freqtradebot.py at 7d9717c](https://github.com/freqtrade/freqtrade/blob/7d9717c/freqtrade/freqtradebot.py): the inspected entry path calls exchange.create_order before adding and committing the Trade. That establishes a submission-to-local-persistence window in that method. Whether startup reconciliation recovers it requires the surrounding recovery code; “permanently loses orders” would be a stronger, unverified conclusion.

These projects are useful references. Their size or popularity cannot validate this project's market-specific cash, cost or accounting behavior.

## Correction sequence and exit evidence

1. **Input controls:** R01 and R02. Preserve data dates and explicit unknown states.
2. **Money controls:** R03 and R04. Separate spendable cash from net settlement, and enforce outstanding margin obligations.
3. **Accounting:** R05, R06, R07 and R08. Fix fee grouping, supported trade classification, atomic validation and attribution.
4. **Research prerequisites:** R09 and R10. Correct tie handling and calendar completeness.
5. Update provenance, handoff and actual test counts.

Preserve the supplied failing fixtures before implementation. Run the original suite and all review cases after each relevant change. Existing tests with incorrect financial expectations must be corrected using an independently documented expectation, not silently retained or weakened. If the public interface changes, port the reproductions without removing the triggering scenario.

For the next review, provide the new commit, commands and output, an R01–R10 resolution table, and remaining account-specific assumptions. Extend the ten minimal cases where noted; they are counterexamples, not a complete certification suite.

**Missing evidence for Phase 2 approval:** corrected input/money controls, reconciled financial outputs, complete supported-session handling, defensible PBO tie semantics, and passing original plus regression tests on the corrected commit.

This does not require abandoning the architecture or MTF. It requires making the simulator a trustworthy measuring instrument. No historical strategy performance or profitable trading edge has been demonstrated by the current synthetic demo.

## Primary sources

Sources checked during this review on 4 November 2026; preserve effective dates when incorporating them into rules.

- **S1:** [Zerodha MTF FAQ](https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/margin-trading-facility-mtf-faqs), especially fees, unpledging, conversion and use of sale proceeds.
- **S2:** [Zerodha MTF calculator and FAQ](https://zerodha.com/calculators/mtf-calculator/), including weekend/public-holiday interest.
- **S3:** [Zerodha CNC/MIS/NRML explanation](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/what-does-cnc-mis-and-nrml-mean) and [partial-delivery brokerage explanation](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/brokerage-charged-for-partial-delivery).
- **S4:** [NSE capital-market clearing circular NCL/CMPT/72384, 19 January 2026](https://nsearchives.nseindia.com/content/circulars/CMPT72384.pdf), referring to the 1 February live trading session and NSE/CMTR/72349.
- **S5:** [Zerodha charges](https://zerodha.com/charges/) for published fee categories. The ledger still needs broker-statement reconciliation for exact aggregation and rounding.
