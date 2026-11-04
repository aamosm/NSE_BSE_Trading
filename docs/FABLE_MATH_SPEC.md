# Quantitative specification for Fable

This is a research assignment, not a claim that the equations create an edge. Read RESEARCH_BRIEF.md and SOURCE_PACK.md first. Do not add live execution or MTF.

## Deliverables, in dependency order

1. A data-readiness report listing what can actually be modeled with the available files.
2. A mathematical specification with explicit labels, information sets, assumptions, units and timestamps.
3. A small preregistered candidate registry. Every failed/tuned configuration remains in it.
4. Pure forecasting and portfolio functions with synthetic, hand-worked checks.
5. A leakage-resistant evaluation runner. Calibrate and train only within training windows.
6. A model card per candidate with untouched-period results and limitations, or a clear statement that data is insufficient.

Do not fill missing datasets with invented examples and then call the results historical performance. The included synthetic demonstration has no evidentiary value for profitability.

## 1. Information and labels

Let I(t) contain only observations available to the decision process by time t. A feature transform X(t) and its fitted parameters must be functions of training information available by t.

For an eligible security i and horizon h, define gross total return:

    R(i,t,h) = [value of one original share plus entitled distributions at t+h] / entry reference value at t - 1.

State corporate-action treatment precisely. Adjusted price series may be useful for features, but raw prices, quantities and actual cash entitlements are required for execution/accounting. Never double-count dividends through both adjusted prices and cash credits.

Execution labels must start at the first realistically tradable price after the decision and data latency, not at the same bar close used to calculate the signal. Define separate intraday, swing and core labels. A label's end timestamp is needed for purging overlapping training observations.

For quantity q, define a cost-dependent net outcome:

    NetPnL = q*(exit execution price - entry execution price) - buy fees - sell fees - applicable DP - other attributable costs.

Subtract operating costs at portfolio/account level. Do not allocate the same monthly API cost independently to every trade.

Do not claim a single quantity-independent probability of net profit when fixed costs make profitability depend on q.

## 2. Initial candidate family

Use simple models as serious controls:

- Regularized linear/rank models using point-in-time quality, value and 12–1 momentum features for core portfolios.
- Event regressions using standardized numerical surprise and structured text facts for swing holdings.
- A narrowly defined intraday reversal/continuation candidate conditioned on spread, volatility, turnover and time of day.

Begin with one model per family and a limited parameter grid. Add gradient boosting or other nonlinear models only after documented baseline comparisons. Deep sequence models and reinforcement learning are not justified merely by available compute.

Financial-statement normalization must handle missing/negative denominators, sector differences and reporting currency. Winsorization cutoffs, sector normalizers, imputation and feature selection are training-fitted parameters.

## 3. Conditional distribution and calibration

Each forecast must supply horizon, mean return estimate, q10/q50/q90, uncertainty in the estimated mean, probability of positive outcome, sample size, model version and calibration record.

Suggested evaluation:

    Brier = mean[(p - y)^2], where y is the defined binary event.
    Pinball(τ) = mean[(τ - 1{y < qτ}) * (y - qτ)].

Report quantile coverage and sharpness, Brier/log loss, calibration by bins and by regime, and discrimination separately. A high rank correlation does not imply calibrated probabilities. Probability must refer to a stated event and horizon.

Use blocked/clustered resampling for uncertainty where temporal or event dependence exists. Do not call mean ± 2 standard errors a valid 95% interval without checking its assumptions. The base's uncertainty penalty is a heuristic gate, explicitly not such a guarantee.

Preserve tails: scenario stresses should include gaps, correlations rising, missing exits and price limits. Quantile crossing must be prevented or repaired with a documented method fitted without using the holdout.

## 4. Event-analogue model

For historical event j, let z_j be pre-decision event/context features and y_j its subsequently realized outcome. Fit the feature scaling, embeddings and distance weights inside the training fold.

One research candidate:

    a_j = exp[-distance(z_new,z_j)^2 / bandwidth^2] * recency_weight_j.
    normalized_weight_j = a_j / sum(a).
    n_effective = [sum(a)]^2 / sum(a_j^2).
    local_mean = sum(normalized_weight_j * y_j).
    shrunk_mean = shrinkage * local_mean + (1-shrinkage) * broader_prior.

Tune bandwidth, recency and shrinkage inside training. Exclude future events, duplicate articles and overlapping outcomes from the same event cluster. A small effective count or out-of-distribution event should produce abstention. Compare to the same model without analogue features.

Do not turn embedding cosine similarity directly into a probability of a stock rising.

## 5. Covariance and cross-horizon consistency

Sample covariance becomes unstable with many securities and limited history. Evaluate shrinkage:

    Sigma_hat = (1-delta) * sample_covariance + delta * structured_target.

Estimate delta and the target without holdout leakage; compare stable alternatives [S17]. Check positive semidefiniteness and conditioning. Daily covariance cannot be pasted into a 60-minute optimizer without a stated mapping and validation.

A core/swing/intraday mix needs either separate risk budgets with a common portfolio risk layer or a coherent multi-period model. Different sleeves may hold the same company, so aggregate exposure by ISIN and relevant common factors. Reserve real cash once.

## 6. Cost-aware allocation

Let w be resulting portfolio weights and Δw the trades. One candidate objective:

    maximize conservative_expected_return(w)
             - lambda * portfolio_risk(w)
             - estimated_cost(Δw)
             - uncertainty_penalty(w).

Conservative means and covariance should be estimated, not manually tuned until a backtest becomes attractive. Include no-trade regions when expected benefit does not exceed costs.

An alternative tail-risk formulation uses scenario losses L_s(w):

    CVaR_beta(w) = min_a [ a + mean(max(L_s(w)-a,0))/(1-beta) ].

Implement the sign convention carefully: greater loss is worse. Compare a tiny case against manual arithmetic and brute-force enumeration. CVaR is a scenario estimate, not a bound on every possible loss [S18].

Constraints:

- Long-only; no financing, derivative exposure or shorting.
- Integer quantities, lot-size compliance and cash after fees.
- Gross purchase reservations; ineligible/unsettled receipts excluded.
- Company, sector, sleeve and correlated-factor exposure caps.
- Daily/rolling turnover and cost budgets; no trade when net advantage is insufficient.
- Liquidity/participation, spread and security-status constraints.
- Account reconciliation and source freshness before new entries.
- Explicit maximum drawdown response and bounded experiment risk.

Fixed costs and integer shares make the optimization non-convex. Do not silently round a fractional optimum and assume feasibility. Solve a small mixed-integer problem or use a documented rounding/repair procedure, then recompute fees, cash and all constraints [S13, S22].

Compare optimizer allocations against equal weight, inverse volatility and a simple capped rank allocation. Optimizer sophistication cannot repair poor forecasts.

## 7. Exit policy

Implement exits as a versioned policy, not a perfect-top predictor:

- Mandatory horizon/session expiry for the strategy.
- Thesis invalidation or required evidence becoming unavailable.
- Updated expected incremental benefit of holding falls below selling/reallocating after costs.
- Risk/exposure constraints require reduction.
- Predeclared protective loss/tail rules, with gap/circuit failure scenarios.

Test hysteresis/no-trade bands to avoid rapid churn when scores fluctuate near a threshold. Do not repeatedly reset a time limit to conceal a losing trade. Corporate actions and invalid inputs need explicit handling rather than invented fills.

## 8. Walk-forward design

The existing fold helper only creates chronological ranges; it does NOT implement label-overlap purging, nested tuning or grouped calibration.

Build expanding/rolling training windows, inner validation for model choices, then untouched outer test windows. Purge by actual label end times and embargo as required by the horizon. All transforms are refit inside the relevant training set.

Preserve a final chronological holdout. Once its results influence a change, it is no longer untouched; use fresh future paper observations for further confirmation.

Report results across multiple market regimes and sectors, including omitted/failed runs. Use block/bootstrap uncertainty suitable for dependent returns. PBO/DSR are supplementary diagnostics, with explicit tie handling and a count of effective trials [S14, S16].

## 9. Required experiments

Separate two registries:

**Engineering scenarios:** at least 1,000 generated combinations of missing/stale news, duplicate fills/events, gaps, splits, outages, insufficient cash, no liquidity, corrupt files, restart and overlapping proposals. Count executed cases, seeds and failure artifacts. Never call them 1,000 independent strategy tests.

**Strategy trials:** a small preregistered candidate set, with complete parameter history. Compare prices-only, financials, events, text and analogues incrementally. Report every trial, not only winners.

For each candidate test zero/normal/doubled slippage, fee assumptions, latency, missed entries/exits, changed universe, shuffled/lagged text, removal of the best stock/year, and different but reasonable thresholds.

A text feature that still “predicts” when attached to the wrong date/security is a leakage alarm.

## 10. Required outputs

FABLE_REPORT.md: what was implemented, hypotheses, data coverage, actual runs and confidence limits.
MODEL_CARDS/: one file per candidate, including failed candidates.
DATA_REQUIREMENTS.json: missing fields with source IDs, periods, licensing and publication-time requirements.
VALIDATION_RESULTS/: immutable predictions, observations, calibration and portfolio paths.
SEARCH_REQUESTS.md: exact unanswered facts for the searching assistant, with affected code/assumption.

Do not report “ready to trade.” The strongest permitted result is “ready for independently reviewed prospective paper observation.” If evidence is insufficient, return abstention and the next data requirement.
