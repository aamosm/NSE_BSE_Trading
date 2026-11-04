# Reset review and disposition of the previous findings

The previous review is preserved unchanged in reviews/PHASE_0_1_REVIEW.md. Its verdict remains valid for upstream 19d12dc. This reset is not a claim that the old code's ten defects were all repaired.

The user subsequently removed MTF, authorized implementation changes and asked for a research base with read-only Kite connectivity. The active package was separated from the old implementation to avoid continuing to build around its financing lifecycle.

| Old finding | Active disposition |
| --- | --- |
| R01: overwritten snapshot date | New observations preserve publication/receipt times; forecasts have explicit as-of/expiry gates. Full dated security-master ingestion is still the next engineering milestone. |
| R02: missing status defaults safe | Paper sizing requires literal known_status=True and restricted=False, same-day status provenance and a recent non-future quote. Unknown/coerced/stale inputs abstain. Actual eligibility retrieval is not implemented yet. |
| R03: unsettled receipts become spendable | Diagnostic simulation separates pending receipts from cash. Portfolio-wide reservations and exact exchange settlement remain required before certification. |
| R04: MTF margin shortfall | MTF is outside the active package; old code retained only in archive. |
| R05: MTF unpledge grouping | Not an active feature or cost. |
| R06: same-day CNC fees | Intraday uses an explicit fee style; unsupported same-day delivery netting is blocked in diagnostics. Complete order/day matching remains future work. |
| R07: partially applied split | Active simulator has no split mutation path. Corporate actions are explicitly unverified, and cannot be silently treated as handled. |
| R08: conversion-fee attribution | MTF conversion removed from active scope. |
| R09: PBO tie optimism | Old selection metrics are not imported. Fable must implement and independently test its chosen selection diagnostics, including ties. |
| R10: missing Budget Sunday | No claim of a complete hard-coded exchange calendar. The collector weekday window is labeled a convenience schedule; dated calendar ingestion remains required. |

## Status after Claude's integration (4 Nov 2026, branch cash-research-reset)

The cash-only rules engine and metrics library were ported back into the active package, without MTF. All 10 legacy counterexamples were first re-run against upstream 19d12dc on Windows / Python 3.13.7, and all 10 failed, as the review reported.

| Finding | Status now | Evidence |
| --- | --- | --- |
| R01 stale snapshot date | **Fixed by design**: the overwriting replay is not active. Paper proposals pass the caller's snapshot unchanged to the engine, which blocks `STALE_SNAPSHOT` | `test_r01_stale_snapshot_date_is_not_overwritten_or_accepted`; `test_exchange_rule_failures_block_the_paper_proposal[as_of]` |
| R02 omitted status = safe | **Fixed**: `InstrumentSnapshot` status fields default to `None` (unknown) | `test_r02_omitted_security_status_blocks_instead_of_defaulting_to_safe` |
| R03 netted receipts spendable | Diagnostic simulator keeps receipts pending. The ledger is not active, so this remains open for the future cash paper account (milestone F) | — |
| R04, R05, R08 | Not applicable (MTF removed) | — |
| R06 same-day CNC round trip | Diagnostic simulator blocks it (`SAME_DAY_DELIVERY_NETTING_UNSUPPORTED`); the engine warns `INTRADAY_REVERSAL_OF_DELIVERY`. Intraday reclassification is open for milestone F | existing tests |
| R07 partial split mutation | Ledger not active. Since 5 Nov 2026 `corporate_actions.py` derives adjusted series and position effects as pure functions (no mutation, double application refused). Atomic application in the paper ledger remains milestone F | `test_corporate_actions.py` |
| R09 PBO tie optimism | **Fixed**: midranks for out-of-sample ties | `test_r09_pbo_midranks_ties_instead_of_ranking_them_as_wins` (review's example → PBO 0.5) |
| R10 Budget Sunday | **Fixed**: 1 Feb 2026 is a weekend trading day at standard timings, T+1 settlement on 2 Feb (NSE/CMTR/72349, NCL/CMPT/72384); NSE 2026 = 246 sessions | `test_r10_*` (3 tests) |

## Review of 3513d33 (GPT, 4 Nov 2026): section 3 of the consolidated handoff

| Finding | Status (5 Nov 2026) | Commit | Evidence |
| --- | --- | --- | --- |
| 1. Snapshot chronology: dedup decided the latest state; yesterday's trades shown as today's; missing became zero | **Fixed.** Latest eligible receipt + completed batch decide the state; first-known time kept separate; per-section OK/STALE/UNAVAILABLE/MALFORMED/MISSING; trade book attributed to a session only after its open; unknown numbers stay unknown | `2d53906` | `test_snapshot_chronology.py` (A→B→A, missing kind, incomplete batch, no-trade day, pre-open book, legacy migration) |
| 2. Time and fee inputs: incoherent decision/submission time; caller-supplied BSE fee group | **Fixed.** Inputs known by decision time, freshness re-checked at submission, >120 s → REVALIDATION_REQUIRED; BSE group from the snapshot series; backtest group only from dataset metadata | `1472281` | `test_costs_and_decision_time.py` |
| 3. Authentication/errors | **Fixed.** Single-use, hashed, 10-minute state through `redirect_params`; exact callback path; finite read deadline (90 s total) and 5 s idle connection timeout; mandatory account check; enumerated error labels; env allowlist with accurate refusal wording; next-06:00 expiry fix; research layer imports no broker client | `e4544e1`, `b0f478c` | `test_login_flow.py`, `test_kite_login.py`, `test_webapp.py` |
| 4. Corporate actions: Kite history already adjusted | **Foundation built, history missing.** Provider/exchange/derived series separated with vintages; double adjustment refused; quantity, entitlement and dividend-payment timing modelled; provider-vs-exchange reconciliation function. Representative real cases not reconciled yet (no official action history collected) | `f431de9` | `test_corporate_actions.py` |
| 5. Costs: STT rounding, stamp, DP | **Basis implemented, reconciliation pending.** Day-level STT per security/side rounded to the rupee (Zerodha examples reproduced); stamp allocation explicitly UNRESOLVED; DP reconciled from the funds statement. Needs one real contract note and funds statement | `1472281` | `test_costs_and_decision_time.py` |
| Calendars: Muhurat and settlement circulars | **Fixed.** CMTR76941 session table and CMPT77037 settlement encoded; NSE 2026 trading and settlement holidays agree with NSE's APIs | `e605514`, `d7383b4` | `test_muhurat_2026.py`, `test_public_data.py` |

## What changed

The runtime now provides a narrow REST adapter, private evidence store, bounded history downloader, RSS evidence ingestion, normalized external-trade observations, diagnostic simulations, immutable experiment events, a forecast contract and a local status page.

There is no trained model or autonomous trading strategy. A simple baseline is kept as a control against which later complex models must justify themselves.

## Additional boundaries checked

- Write routes are denied before transport, including position conversion and GTT. The low-level HTTP function also checks the allowlist.
- Token exchange is the only POST. No generic order methods or live flag exist.
- Historical export checks current token/symbol/exchange identity; ISIN mapping remains an explicit external verification requirement.
- Later-received news is unavailable to earlier decisions. Source content and repeated receipt times are retained separately.
- Backtest purchases use later bar opens, with logged input availability; future changes are tested for their effect on earlier decisions.
- Intraday runs fail if an exit cannot be represented; no convenient end-of-test close is invented.
- Money uses Decimal; nonfinite values and naive timestamps are rejected.
- Status text escapes untrusted input, serves from loopback and exposes no action controls.

## Still not independently demonstrated

A deployed VPS and the phone login through Tailscale (prepared, not run); reconciliation with a real contract note; official corporate-action history; real historical strategy performance; full Indian-market calendars/restrictions/corporate actions; complete account reconciliation; multi-asset coordination; statistical forecasting or calibrated alpha.

The test report in HANDOFF.md applies to the active reset only. The old 211 tests remain in the archive for historical reference and are not silently counted as tests of this new package.
