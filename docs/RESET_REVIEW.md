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
| R07 partial split mutation | Ledger not active; no split path exists. Must be atomic when corporate actions are built (milestone C) | — |
| R09 PBO tie optimism | **Fixed**: midranks for out-of-sample ties | `test_r09_pbo_midranks_ties_instead_of_ranking_them_as_wins` (review's example → PBO 0.5) |
| R10 Budget Sunday | **Fixed**: 1 Feb 2026 is a weekend trading day at standard timings, T+1 settlement on 2 Feb (NSE/CMTR/72349, NCL/CMPT/72384); NSE 2026 = 246 sessions | `test_r10_*` (3 tests) |

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

Real Kite authentication and response compatibility on this user's account; Windows ACL/setup behavior; live official feed accessibility; a deployed VPS; real historical strategy performance; full Indian-market calendars/restrictions/corporate actions; complete account reconciliation; multi-asset coordination; statistical forecasting or calibrated alpha.

The test report in HANDOFF.md applies to the active reset only. The old 211 tests remain in the archive for historical reference and are not silently counted as tests of this new package.
