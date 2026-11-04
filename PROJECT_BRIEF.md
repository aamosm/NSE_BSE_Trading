# Cash-only NSE/BSE research base

The goal is a part-time, evidence-driven research and eventual paper portfolio system. It should study prices, financial statements, company events and relevant news; propose integer-share allocations across distinct horizons; retain the reasons for every proposal; and explain recorded numbers in plain language without a runtime LLM.

The final system is not built yet. This reset provides the data boundary, evidence store, diagnostic backtests, forecast contract, conservative paper sizing and local status page on which to build it.

## Decisions made by the user

- NSE and BSE stocks only.
- Remove MTF from the active product.
- Connect Kite for data while keeping all real buys and sells disabled.
- Research intraday opportunities and longer-horizon portfolios.
- Use Claude for engineering, Fable for deeper quantitative work, then a separate testing/review pass.
- Return the entire modified repository as a ZIP with research, prior review and instructions.

## Corrected objective

Estimate a distribution of possible returns over a defined horizon, after costs and with uncertainty. Buy proposals require an evidence-supported advantage over cash/alternatives and acceptable exposure. Sell proposals should follow risk, revised forecasts, costs and horizon expiry.

“Cannot go lower,” “cannot go higher” and “will only appreciate” are not admissible claims. A price of ₹20 does not imply cheap valuation or safe trading. An algorithm may correctly choose cash or make no intraday allocation for long periods.

## Current limits

This package has no trained forecasting model, multi-asset optimizer, validated Indian trading edge, automated statement reconciliation or live broker execution. The simple baselines are diagnostic controls. Their simplicity is deliberate; they are not the requested final strategy.

Kite is a broker/market-data source, not a comprehensive historical-news or financial-statement database. Required additional sources and their limitations are specified in docs/RESEARCH_BRIEF.md and docs/SOURCE_PACK.md.

The previous ₹10,000 capital figure is retained as a research example. It does not establish that recurring services can be funded from investment profits.
