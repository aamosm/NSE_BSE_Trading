# Cash-only NSE/BSE research base

The goal is a part-time, evidence-driven research and eventual paper portfolio system. It should study prices, financial statements, company events and relevant news; propose integer-share allocations across distinct horizons; retain the reasons for every proposal; and explain recorded numbers in plain language without a runtime LLM.

The final system is not built yet. Milestone 1 (5 Nov 2026) provides the data boundary, evidence store, official exchange-file collection, daily rule inputs, a calendar-driven scheduler, a private phone app with the official Kite login, deployment files, diagnostic backtests, a forecast contract and conservative paper sizing.

## Decisions made by the user

- NSE and BSE stocks only.
- Remove MTF from the active product.
- Connect Kite for data while keeping all real buys and sells disabled.
- Research intraday opportunities and longer-horizon portfolios.
- Claude is the implementation owner. GPT reviews, searches and plans. Fable is used for exactly two heavy-reasoning sessions: research design freeze, then evidence audit (docs/ROADMAP.md section 3).
- Revised 4 Nov 2026: run on one small private Linux server (about US$12/month) with an installable private phone app over Tailscale; the laptop is used until the server exists. Kite (₹500/month) is already paid; new recurring services need a stated purpose and budget.
- Initial simulated capital ₹10,000. Execution is simulated only; no live-mode toggle. A future live system would need its own explicit project decision.
- Kite app credentials are stored privately on the machine that uses them (`.env`, user-only). The broker password, PIN and TOTP seed are never stored, and the daily Zerodha login is always done by the owner.

## Corrected objective

Estimate a distribution of possible returns over a defined horizon, after costs and with uncertainty. Buy proposals require an evidence-supported advantage over cash/alternatives and acceptable exposure. Sell proposals should follow risk, revised forecasts, costs and horizon expiry.

“Cannot go lower,” “cannot go higher” and “will only appreciate” are not admissible claims. A price of ₹20 does not imply cheap valuation or safe trading. An algorithm may correctly choose cash or make no intraday allocation for long periods.

## Current limits

This package has no trained forecasting model, multi-asset optimizer, validated Indian trading edge, automated statement reconciliation or live broker execution. The simple baselines are diagnostic controls. Their simplicity is deliberate; they are not the requested final strategy.

Kite is a broker/market-data source, not a comprehensive historical-news or financial-statement database. Required additional sources and their limitations are specified in docs/RESEARCH_BRIEF.md and docs/SOURCE_PACK.md.

The previous ₹10,000 capital figure is retained as a research example. It does not establish that recurring services can be funded from investment profits.
