# Metrics register

Status: definitions frozen on 4 November 2026, before any strategy result exists (Validation Plan: "definitions … must be preregistered before selecting results"). A change to a definition gets a dated entry in §12 and invalidates comparisons across the change.

Each metric below is marked with where it stands. **Implemented** means code exists in `src/marketlab/metrics/` (or the named module) with hand-worked tests in `tests/test_metrics.py`. **Phase N** means it is defined here but not built yet.

## 1. Conventions (apply to everything below)

| Topic | Rule | Why |
| --- | --- | --- |
| Money | Rupees as `Decimal`, rounded to the paisa half-up only where a charge or ledger posting is rounded | Accounting must not drift. Statistics (ratios, volatility) are floats because they are estimates |
| Valuation series | End-of-session **net liquidation estimate** (§2), not cash or buying power | Borrowed MTF money is not equity |
| Returns | Daily **time-weighted** returns with deposits/withdrawals at the start of the day: `r_t = V_t / (V_{t-1} + F_t) − 1` | Deposits must never show up as profit (`test_deposits_are_not_returns`) |
| Periods per year | Number of regular sessions in the loaded exchange calendar year. **NSE 2026 = 245** | 252 is a US number; 365 inflates a daily Sharpe by ≈1.22x |
| Risk-free rate | Must be passed explicitly as a per-period rate. Source: the 91-day T-bill cut-off yield at each auction, converted with `(1+R)^(1/P) − 1`. Passing 0 is allowed only as a labelled choice | Indian rates (~5–7%) are material. A default of 0 inflates Sharpe |
| Sample statistics | Standard deviation uses n−1; skewness/kurtosis use population moment ratios (normal kurtosis = 3) as the PSR/DSR formulas require | Stated so results are reproducible |
| Undefined metrics | Raise `MetricUnavailable` (too few points, zero variance, no losses…). Never a silent 0/NaN/∞ | A missing number must look missing |
| Counterfactuals | Metrics from current-rule replays of older dates carry the counterfactual flag from the charge schedule/rules | Build Guide §10 |
| Costs | Every return is reported **net of all charges and MTF interest**. Gross numbers are shown only next to the net ones | Brief: "separate costs from returns" |

## 2. Account and ledger metrics (Phase 1, from the ledger)

| Metric | Definition |
| --- | --- |
| Net liquidation estimate (NLV) | Settled cash + sale receivables − purchase payables + Σ(qty × mark) − MTF principal − accrued MTF interest − estimated exit costs (labelled estimate) |
| Available cash | Settled free cash − payables − reserved cash. Sale receivables are excluded until settlement (conservative ASSUMPTION; Zerodha lets CNC sale proceeds fund same-day buys, MTF sale proceeds only after T+1) |
| Reserved cash | Cash earmarked by pending entry orders, pending MTF margin calls and the user's buffer |
| Holdings at cost / market value | Per lot: open quantity × average buy price / × mark. Kept separate from cash flows |
| Unrealised P&L | Market value − cost of open lots (gross; costs already expensed) |
| Realised P&L | Gross: sale value − FIFO cost. Net: gross − all charges − MTF interest attributed to the closed slice |
| MTF funded principal | Σ open MTF lots' funded amount (purchase value − initial margin), per lot and in total |
| Accrued MTF interest | Σ daily 0.04% × opening funded balance for each chargeable day (day-count rule in PHASE_1_PLAN.md §4) |
| MTF margin requirement | margin% (VaR + 3/5×ELM, current snapshot) × buy value + MTM loss (buy value − market value, if positive) |
| MTF headroom | Cash blocked for the position + free cash − requirement. Negative ⇒ `MARGIN_SHORTFALL` |
| Gross exposure / leverage | Σ market value / NLV; funded principal / NLV |
| Contributions / withdrawals | Separate equity accounts; excluded from returns |
| Costs by component | Brokerage, STT, exchange, SEBI, IPFT, stamp, GST, DP, pledge, unpledge, square-off, MTF interest: each its own expense account |

## 3. Return metrics (implemented)

| Metric | Function | Definition |
| --- | --- | --- |
| Simple returns | `simple_returns` | `V_t / V_{t-1} − 1` (only for flow-free series) |
| Time-weighted returns | `time_weighted_returns` | §1 formula; `flows[0]` must be 0 |
| Compound return | `compound_return` | `Π(1 + r_t) − 1` |
| Annualised return | `annualized_return` | `(Π(1+r))^(P/n) − 1` |
| CAGR (calendar) | `cagr` | `(V_end/V_start)^(1/years) − 1`, years = ACT/365.25 days |
| Money-weighted return | `xirr` | Root of `Σ CF_i/(1+r)^(d_i/365) = 0`, contributions negative, final value positive; bisection |
| Per-period rate | `per_period_rate` | `(1+R)^(1/P) − 1` |

## 4. Risk metrics (implemented)

| Metric | Function | Definition |
| --- | --- | --- |
| Volatility | `volatility` | sample sd × √P |
| Downside deviation | `downside_deviation` | `√(Σ min(0, r−MAR)² / n) × √P`, n = **all** periods |
| Max drawdown | `max_drawdown` | Deepest `V_t / max(V_0..V_t) − 1`; reports peak, trough and recovery index (None if unrecovered) |
| Drawdown series | `drawdown_series` | As above, per period |
| Ulcer index | `ulcer_index` | `√(mean(dd_t²))` as a fraction |
| Historical VaR | `historical_var` | Loss at the k-th worst return, `k = ⌈n(1−c)⌉`, no interpolation |
| Expected shortfall | `expected_shortfall` | Mean loss of the k worst returns |
| Skewness, kurtosis | `moments` | `m3/m2^1.5`, `m4/m2²` |
| Beta, tracking error | `beta`, `tracking_error` | Sample covariance / variance; sd of active returns × √P |

## 5. Risk-adjusted ratios (implemented)

| Metric | Function | Definition |
| --- | --- | --- |
| Sharpe | `sharpe_ratio` | `mean(r−rf) / sd(r−rf) × √P`; `rf_per_period` is a required keyword |
| Sortino | `sortino_ratio` | `mean(r−MAR) × P / downside deviation` |
| Calmar | `calmar_ratio` | annual return / max-drawdown depth |
| Information ratio | `information_ratio` | `mean(active) / sd(active) × √P` |

## 6. Luck and selection-bias metrics (implemented)

All take **per-period** (not annualised) Sharpe ratios.

| Metric | Function | Definition and source |
| --- | --- | --- |
| Probabilistic Sharpe ratio | `probabilistic_sharpe_ratio` | `Φ((SR−SR*)√(n−1) / √(1 − γ3·SR + (γ4−1)/4·SR²))`. Bailey & López de Prado (2012) |
| Expected max Sharpe of N null trials | `expected_max_sharpe` | `√V[(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))]`, γ = Euler–Mascheroni |
| Deflated Sharpe ratio | `deflated_sharpe_ratio` | PSR with SR* = expected max. N = **every** trial tried, including failures. Bailey & López de Prado (2014) |
| Minimum track record length | `min_track_record_length` | `1 + V·(Φ⁻¹(c)/(SR−SR*))²` observations |
| Probability of backtest overfitting | `probability_of_backtest_overfitting` | CSCV: T×N trial returns in S equal blocks; for each half/half split rank the in-sample winner out of sample; PBO = share of logits ≤ 0. Bailey, Borwein, López de Prado & Zhu (2017) |

## 7. Trade metrics (implemented)

`trade_stats` takes ledger-produced `RoundTrip`s (FIFO slices) and returns:

- count, wins, losses and flat trades;
- win rate on **net** P&L;
- gross P&L, charges, interest and net P&L;
- average win and loss;
- payoff ratio and profit factor;
- expectancy (₹ net per round trip);
- cost share of gross P&L;
- average sessions held.

## 8. Cost, financing and execution metrics

| Metric | Status | Definition |
| --- | --- | --- |
| Round-trip break-even | Implemented: `round_trip_breakeven` | Lowest exit price on a 1-paisa grid covering buy + sell charges, DP, pledge/unpledge (+GST) and MTF interest. Tick rounding not applied, so this is a lower bound |
| Cost in bps of turnover | Implemented: `cost_bps_of_turnover` | charges / traded value × 10,000 |
| Turnover ratio | Implemented: `turnover_ratio` | (buys + sells) / 2 / average NLV over the period |
| Slippage | Implemented: `slippage_bps` | Fill vs decision price, signed so positive = worse for us |
| Cost drag | Phase 1 | Gross TWR − net TWR over the same period |
| MTF carry | Phase 1 | Interest paid / average funded principal; interest as % of net P&L |
| Fill, partial-fill, rejection and cancel rates | Phase 3 | Per order; rejections broken down by reason code |
| Time to fill, lost acknowledgements, duplicate updates ignored | Phase 3 | From the order event log |
| Modifications per order (Kite cap 25), API calls/s, /min, /day (10/400/5,000) | Phase 3/7 | From the rate limiter |
| Reconciliation breaks and their age | Phase 7 | Our positions/cash vs broker snapshots |

### Break-even table (Zerodha schedule observed 4 Nov 2026, NSE, price ₹100)

Generated by `round_trip_breakeven`. Totals include all charges, the ₹15.34 DP charge on delivery/MTF sells, and for MTF pledge + unpledge ₹17.70 each plus interest on ₹7,500 funded.

| Trade | Trade value (₹) | Round-trip cost (₹) | Price rise needed to break even |
| --- | --- | --- | --- |
| Delivery | 500 | 16.48 | 3.30% |
| Delivery | 1,000 | 17.59 | 1.76% |
| Delivery | 2,000 | 19.80 | 0.99% |
| Delivery | 5,000 | 26.50 | 0.53% |
| Delivery | 10,000 | 37.64 | 0.38% |
| Intraday (MIS) | 1,000 | 1.06 | 0.11% |
| Intraday (MIS) | 10,000 | 10.64 | 0.11% |
| MTF, 25% margin, 5 days | 10,000 | 135.34 | 1.36% |
| MTF, 25% margin, 30 days | 10,000 | 210.41 | 2.11% |

What this means for a ₹10,000 account:

- Several small delivery positions are expensive, because the DP charge is per stock per sell day.
- MTF on ₹10,000 needs a >1.3% move just to pay its fixed fees and a week of interest.
- MIS is cheap per trade but is out of policy scope (`Policy.allowed_products` = CNC, MTF).

## 9. Rules-engine and data metrics

| Metric | Status | Definition |
| --- | --- | --- |
| Decisions by outcome and reason code | Phase 3 (codes exist now) | Count of `Decision.codes(BLOCK/WARN)` over a replay |
| Unknown-input block rate | Phase 3 | Share of decisions blocked by `*_UNKNOWN` codes; a high rate means a data gap, not a market signal |
| Snapshot staleness | Phase 2 | Decision time − snapshot `as_of` / publication time |
| Coverage | Phase 2 | Sessions × instruments with complete required inputs / total |
| Revisions | Phase 2 | Number of corrected observations; decisions that used a later-revised value |

## 10. Research evaluation (Phase 5)

Every candidate reports §3–§7 on the validation and final periods, next to three baselines with the same capital, costs and financing rules:

1. Cash (T-bill rate).
2. Buy-and-hold of a Nifty 50 ETF (delivery costs, DP on exit).
3. Equal-weight over the research universe at the same rebalance frequency.

It also reports the trial count, deduplicated effective trials, DSR, PBO, parameter-neighbourhood stability, `NOT_EVALUABLE` count with reasons, and sample size per horizon. The decision rule for promotion is written before the final period is opened.

## 11. Project and engineering metrics (snapshot 4 Nov 2026)

| Metric | Value |
| --- | --- |
| Tests executed / passed / failed / skipped | see `docs/HANDOFF.md` for the latest run |
| Mutation check (rules engine) | 7 of 7 deliberate errors caught |
| Registered sources / rule citations | 31 sources; >40 citations, all provenance-checked by tests |
| Open rule items | 15 (RULES_REGISTER.md §10) |
| Scenario registry (1,200) | PLANNED 1,200; implemented 0; executed 0 |
| Research registry (1,000) | PLANNED 1,000; implemented 0; executed 0 |

## 12. Change log

- 2026-11-04: initial definitions.
