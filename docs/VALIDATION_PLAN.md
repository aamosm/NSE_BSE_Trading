# Validation plan

## Registry status

The JSON files are planned definitions only. All cases/trials initially have status PLANNED. No data, implementation, profitability or successful execution is implied by their presence.

## 1,200 functional combinations

Dimensions:

- 10 scenario families.
- 5 contexts: rising, falling, range-bound, volatile_event, discontinuity.
- 4 starting portfolio states: cash_only, existing_unlevered, existing_funded, reconciled_mixed_manual.
- 3 liquidity levels: deep, moderate, thin_or_unavailable.
- 2 financing modes for the proposed action: cash, mtf.

An existing funded position is permitted as the starting state even when the proposed action uses cash. In a cash-only financing-lifecycle case the expected result may be rejection of a funding operation. Implement explicit assertions; do not count a no-op as a meaningful test.

Every case references family-level invariant requirements. A case is implemented only when it has a reproducible fixture and exact expected observations. Count expected rejections as successful behavior only when the reason and absence of side effects are verified.

Beyond this matrix, add specific exchange/settlement/MTF cases the dimensions miss. The matrix does not claim exhaustive coverage of all variables.

## 1,000 research candidates

Dimensions: raw event weight 0/0.25/0.5/0.75/1; raw momentum weight same; analogue history 24/36/60/84 months; horizon 1/5/20/60/252 sessions; cash_only versus mtf_eligible_with_caps. Raw fundamental weight is fixed at 1; normalize the three top-level weights. Analogue windows control evidence construction, not a fourth secretly optimized weight.

MTF policy does not force borrowing. Both financing policies can produce the same trades. Deduplicate identical outputs when interpreting effective search size, and retain the original experiment registry.

These are starting hypotheses. Definitions, data requirements, fee schedules and evaluation rules must be preregistered before selecting results. Unsupported histories/horizons must be marked NOT_EVALUABLE with a reason, never reported as passed or filled with invented data.

## Execution plan

1. Create independent hand-worked accounting examples.
2. Implement the simulator and validate ten diverse configurations.
3. Freeze data sources, features, strategies, rule versions and seeds.
4. Select chronological development, validation and untouched final periods with adequate horizon coverage.
5. Run bounded local jobs; cache immutable feature inputs.
6. Record every trial including failures, duration, effective policy, costs and data gaps.
7. Analyze multiple testing and parameter-neighborhood stability before choosing a candidate.
8. Inspect the final evaluation only for the frozen selection. Retuning starts a new research cycle and consumes new evaluation evidence.
9. Observe prospective paper decisions; record all changes and compare executable fills/costs.

## Required result files

scenario_results.json: planned, implemented, executed, passed, failed, skipped and not_evaluable counts with per-case evidence.

research_results.parquet or equivalent: trial IDs, as-of datasets, software commit, periods, return, drawdown, cost/interest breakdown, exposure, turnover, uncertainty and baseline comparison.

evaluation_report.md: sample sizes, market coverage, leakage risks, rejected hypotheses, selection procedure, cost sensitivity and limitations.

## Meaningful adversarial checks

- A stock falls through the intended stop and cannot exit at that price.
- A buy is executed by the broker but the submission response is lost.
- An order update arrives twice and later an older update arrives.
- The user places a manual trade while the app has a proposal pending.
- An MTF margin requirement changes after entry.
- A filing is corrected; the old historical decision retains the old version.
- A stock is suspended or delisted and must not disappear from results.
- An LLM returns a wrong currency unit or obeys an instruction embedded in a document.
- An API budget cap or model outage occurs while funded positions remain.
- An approval expires, or cash/margin changes after approval.

## Release distinction

Correctness tests support software reliability. Historical strategy results support a research hypothesis under their assumptions. Forward paper operation supports execution realism. None individually establishes future profit.
