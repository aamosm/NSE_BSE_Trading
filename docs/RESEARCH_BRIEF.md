# Research brief for Claude and Fable

Prepared 4 November 2026. Source IDs refer to SOURCE_PACK.md. Literature is evidence for hypotheses, not proof that the effect exists in today's Indian cash market after this account's costs.

## 1. What “buy low, sell high” must mean mathematically

An absolute future minimum/maximum is unknowable in real time. A label such as “the lowest price in the next month” can be calculated after the month for evaluation, but putting that label into today's input leaks the future.

Use a specified horizon and distribution: expected return, lower/median/upper return quantiles, probability of a positive net return, and uncertainty in those estimates. “Price looks stretched relative to its recent range” is a feature. “It cannot fall farther” is not.

An optimal exit is a sequential decision under uncertainty. Compare the distribution from holding one more period with selling and allocating elsewhere, after incremental costs. The future realized maximum is an oracle benchmark only, never an executable strategy. Stop prices are intended responses, not guaranteed loss bounds when gaps, circuits or missing liquidity prevent fills.

## 2. Why brokers make money and why that does not prove a trading edge

A broker supplies execution, custody-related services and account infrastructure. It can collect fees on customer activity regardless of whether a particular customer wins. Zerodha publishes zero delivery brokerage, intraday brokerage and other service charges [S04]; taxes and exchange levies are not all broker profit. Its historical business disclosure describes dependence on intraday and derivatives brokerage [S20]. The proposed app is a capital allocator, not a broker, and cannot inherit that business model by trading more.

SEBI's 2024 equity-cash study reported losses for roughly seven in ten individual intraday traders in FY23 [S15]. This is a historical population statistic, not a forecast of this system's result. It does justify demanding strong out-of-sample evidence before enabling an intraday sleeve.

## 3. Separate three research families

| Family | Initial horizon | Hypothesis to test | Required information | Main failure mode |
| --- | --- | --- | --- | --- |
| Core quality/value/momentum | 3–12 months, reviewed weekly/monthly | Profitable, reasonably valued businesses with supportive trends may outperform a suitable benchmark | Point-in-time financials, valuation, balance sheet, sector, total returns and historical membership | Paying too much, structural deterioration, long factor drawdowns |
| Swing/event response | 2–20 sessions | A genuine surprise may be incorporated gradually or may produce an overreaction | Timestamped filings, expected/actual event values, price/volume response and event similarity | Surprise already priced, duplicate news, revisions, small sample |
| Intraday liquidity/reversal or continuation | 5–120 minutes, flat before cutoff | Conditional short-horizon return behavior after cost and liquidity filters | Reliable intraday bars plus spread/depth observations, eligible securities and session rules | Costs exceed edge, stale quotes, circuits, queue/fill assumptions |

Momentum literature studies continuation across stocks over months [S10]. Profitability research supports examining profitability alongside value [S11]. Text-based earnings research gives a concrete reason to test structured narrative information rather than merely adding a generic sentiment score [S12]. These studies largely concern other markets; replication in NSE/BSE is required.

Begin with a small preregistered set of interpretable models. Complexity earns its place through incremental untouched-period performance, calibration and stability.

## 4. Feature inventory with explicit missingness

| Group | Candidate variables | Availability discipline |
| --- | --- | --- |
| Price/trend | 1/5/20/60/252-session returns, 12–1 momentum, volatility, drawdown, gap, range position | Completed observations only; corporate-action-adjusted research series |
| Liquidity | Median traded value, spread, depth, zero-volume frequency, participation, impact estimate | Separate last-traded price from executable bid/ask and size |
| Quality | Gross profitability, operating margin, cash conversion, accruals, leverage, interest coverage | Latest statements actually published by the cutoff, with units and period |
| Valuation | Earnings/free-cash-flow yield, book-to-price, enterprise-value ratios | Compatible accounting periods; avoid mechanically ranking negative denominators |
| Events | Results, guidance, orders, buybacks, dividends, splits, management/auditor changes, litigation | Announced date, publication time and effective date are different |
| Ownership/governance | Promoter holdings/pledges, insider transactions, dilution, auditor qualification | Original disclosure dates, not the latest website snapshot |
| Context | Sector-relative returns, market volatility/breadth, rates, INR/oil exposure, scheduled macro releases | Vintage data and sector-specific relationships |
| Evidence quality | Primary/secondary source, duplication cluster, contradiction, extraction reliability, staleness | A quality control, not a price probability |

Do not require thousands of redundant variables. Missingness is itself recorded; critical execution/risk fields block action. Optional missing features require an explicitly trained missing-data treatment, not silent zeros.

For a small intraday universe, filter on turnover, spread, depth, lot size and restrictions. Low nominal share price and low market capitalization are different. Initially exclude SME lots, trade-for-trade/periodic auctions, suspended securities and unknown surveillance states. The automated point-in-time filter is a required next-stage deliverable, not already implemented here.

## 5. News and upcoming events

Start with exchange announcements, financial results, corporate actions and company investor-relations documents [S05–S07]. General news supplies context and a discovery queue. Two newspapers repeating one filing are one underlying source, not independent corroboration.

Extract facts into typed fields: security/ISIN, event type, reporting period, amount, currency/unit, actual value, stated comparison, announced/effective/publication times, source span, hash and contradictions. Separate consolidated versus standalone financials. A number in crores must not silently become rupees.

Upcoming-event schedules are versioned forecasts of a date, not proof of the event's outcome. Board-meeting notices and results calendars can change. Macro dates come from the issuer's official calendar [S19]. Do not invent analyst consensus if no licensed timestamped consensus source is available; test alternative surprise definitions explicitly.

The current RSS module stores evidence only. Automatic entity mapping, document retrieval, numerical extraction and feature construction remain for Claude/Fable. A current LLM may know what happened after an old article: historical text experiments must constrain extraction to supplied spans and test for hindsight contamination. Offline extraction is preferable to running a general agent on every tick.

## 6. Event analogues

An analogue engine needs event-type-specific definitions. A large customer order, an earnings miss and a litigation ruling should not be pooled merely because their sentiment is positive or negative.

Construct similarity using only information available before each decision: sector, company size, valuation, leverage, event magnitude normalized by revenue/market value, surprise, preceding return, volume response, market regime and source quality. Fit scaling and distance weights on the training window only.

Report the number of independent events, effective neighbor count, dispersion and age. Overlapping events in one company are correlated observations. Weight nearby cases, shrink their estimated response toward a broader prior, and abstain when the effective sample is small or the new case is far outside training support.

Test whether analogues improve prediction over a non-analogue model using the same data. Semantic resemblance alone does not establish causation or repeatability.

## 7. Portfolio allocation

Allocation must operate across the whole account, not evaluate attractive stocks independently and spend the same cash repeatedly. Use ISIN to aggregate NSE/BSE listings. Account for existing positions, pending/reserved cash, unsettled receipts, sector/common-factor concentration and integer share sizes.

Use a cost-aware constrained objective and stable covariance estimates [S13, S17]. Fixed sale charges matter at this capital size; they create useful no-trade regions. A mathematically optimal fractional allocation may be impossible with whole shares.

The example caps in research.py are engineering defaults, not learned optimal ratios or personal investment advice. The current function is a single-entry gate. Fable must build and test a serialized multi-asset planner and an explicit exit/rebalance policy.

Core holdings are reviewed on fundamentals and portfolio contribution, not sold just because another signal briefly outranks them. Intraday holdings cannot silently become long-term investments to avoid recognizing a loss.

## 8. NSE versus BSE

The same ISIN represents the same security across listings; it does not diversify the portfolio twice. Prices, spread, depth, fees and available volume can differ. Evaluate an executable all-in price rather than comparing two last-traded prices.

Zerodha documents exchange interoperability [S08]. That does not make two asynchronous legs atomic or eliminate execution risk. Exchange-specific eligibility, settlement, holdings availability and product behavior still require verification. The active base does not implement cross-exchange arbitrage.

A ₹1 displayed difference may disappear after spread, fees, latency or an unfilled second leg. Start with choosing one eligible venue for a hypothetical order, not an assumption of guaranteed arbitrage.

## 9. Economic feasibility at ₹10,000

The published Kite paid plan is ₹500/month per API key [S01]. That alone is ₹6,000/year, or 60% of an unchanged ₹10,000 starting principal, before hosting, other data, transaction costs and taxes. This is a cost hurdle, not an expected return.

For illustration, even a hypothetical 20% gross year on ₹10,000 yields ₹2,000 before those costs. Do not budget on that return; the arithmetic simply shows the mismatch. Development can be worthwhile as learning and an experiment, while service bills are funded separately.

Use existing hardware initially. A small cloud collector is optional; a published 1 GiB example is US$6/month before taxes/add-ons [S21]. Train models locally or in bounded batch jobs. Cache immutable source documents, deduplicate text and set explicit request/token/time budgets. Subscriptions used interactively do not automatically include production API usage.

No runtime AI API is required by this base. Later extraction should have a hard monthly rupee cap and a fallback to stored evidence/no new prediction.

## 10. Historical testing that answers the actual question

First validate the dataset: delisted companies, symbol/ISIN changes, original index membership, corporate actions, publication lag, restrictions, calendars and fees. Kite candles alone do not solve these [S02, S03, S09].

Then define training, tuning and untouched chronological periods. Purge training labels whose future outcome windows overlap validation; use an embargo matched to the label horizon. Fit scalers, feature selection, embedding transforms, universe rules and calibration inside training only. Keep companies/events grouped when dependence requires it.

Compare with cash, an implementable passive benchmark, equal-weight eligible stocks and simple factor baselines. Use total-return benchmarks where appropriate and distinguish index returns from a realistically investable ETF with its own costs.

Run ablations: prices only; plus financials; plus events; plus text; plus analogue features. A more complex model must improve net outcomes or risk in repeated untouched tests. Measure drawdown, turnover, cost drag, calibration, forecast error, holding time, tail loss, capacity and net rupees after recurring costs. Win rate alone is insufficient.

Count all attempted configurations. DSR and PBO address forms of selection bias [S14, S16]; they do not repair future leakage, bad data or unrealistic execution. One thousand variations can increase overfitting. The 1,000-case engineering campaign and the statistical strategy search must be reported separately.

## 11. Deployment rhythm

Initially: daily manual Kite login; master snapshot once a day; quote/account polling every five minutes during the collection window; official event collection every 15–30 minutes if the feed permits; after-close normalization/quality checks; weekly bounded model evaluation; monthly backup restore drill.

For a validated intraday experiment, add a WebSocket recorder, reconnect/gap detection, timestamp health and resource measurements. The current REST collector is not a low-latency execution feed. Disable paper signals when required data is stale.

The user must be able to read what data is missing, why the system abstained, what changed since yesterday and which evidence drove a proposal. A fluent explanation must never conceal an unknown or substitute for a model record.

## 12. What would change our mind

Promote a candidate only after independent implementation checks, point-in-time data review, stable net results across several regimes and untouched periods, sensible calibration, adverse cost/fill stress and prospective paper observation. Repeated review of the same holdout consumes that holdout.

If no candidate beats the realistic benchmark after service costs, retain the system as a research dashboard. Do not lower the benchmark, increase risk or add variables merely to force a positive answer.
