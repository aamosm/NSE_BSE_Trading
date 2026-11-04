# Source pack

Checked 4 November 2026. Primary sources only for implementation claims. Links are references, not a grant to bulk scrape, redistribute, or bypass access controls. Preserve effective dates, source payloads and retrieval times when incorporating rules.

| ID | Source | What it supports / important limitation |
| --- | --- | --- |
| S01 | [Zerodha Kite API FAQ](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs) | Paid ₹500/month per API key includes market/historical data; Personal excludes them. Authentication and app setup. Some prose dates conflict with the dedicated static-IP page; use S23 for that rule. |
| S02 | [Kite historical candles](https://kite.trade/docs/connect/v3/historical/) | OHLCV endpoints, intervals and continuous-futures limitations. Not a historical news/fundamentals archive. |
| S03 | [Kite instruments/quotes](https://kite.trade/docs/connect/v3/market-quotes/) | Daily instrument dump, quote endpoints, token/symbol fields. Dump prices are not a live quote and the schema is not an ISIN security master. |
| S04 | [Zerodha charges](https://zerodha.com/charges/) | Published brokerage, taxes, BSE group differences, DP/IPFT and service fees. Account-specific classification and contract-note rounding still need reconciliation. |
| S05 | [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) | Corporate disclosures with broadcast dates/times and attached documents. Not an unrestricted documented API. |
| S06 | [NSE RSS directory](https://www.nseindia.com/static/rss-feed) | Feeds for announcements, results, meetings and corporate actions. Copy the actual feed URL from the official page; current live XML endpoint was not authenticated or automatically tested in this environment. |
| S07 | [SEBI equity data-source directory](https://www.sebi.gov.in/curation/equity_cash_market.html) | Official links to exchange price, corporate and compliance sources. BSE announcements at https://www.bseindia.com/corporates/ann.html returned 403 here; use browser export/licensed access rather than bypassing it. |
| S08 | [Zerodha interoperability explanation](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/interoperability-of-exchanges) | NSE/BSE clearing interoperability and exchange selection. Does not establish a guaranteed arbitrage opportunity. |
| S09 | [NSE settlement cycle](https://www.nseindia.com/static/products-services/equity-market-settlement-cycle) | Trading and settlement calendars differ; holidays and settlement types matter. The diagnostic engine's next-dataset-session rule remains an approximation. |
| S10 | [Jegadeesh & Titman, momentum](https://www.nber.org/papers/w7159) | Research hypothesis for intermediate-horizon momentum; not an India-specific current net-profit guarantee. |
| S11 | [Novy-Marx, gross profitability](https://www.nber.org/papers/w15940) | Profitability/value research rationale. Requires point-in-time fundamentals and local replication. |
| S12 | [PEAD.txt research](https://www.frbsf.org/research-and-insights/publications/system-research-philadelphia-fed/2024/05/pead-txt-post-earnings-announcement-drift-using-text/) | Text may contain information beyond earnings numbers. It does not validate generic LLM sentiment or today's Indian market. |
| S13 | [Boyd et al., multi-period trading](https://stanford.edu/~boyd/papers/cvx_portfolio.html) | Expected return/risk/cost optimization framework. The authors explicitly separate allocation from forecasting. |
| S14 | [Bailey & López de Prado, Deflated Sharpe Ratio](https://doi.org/10.3905/jpm.2014.40.5.094) | Selection bias and non-normality; not a cure for bad execution or information leakage. |
| S15 | [SEBI 2024 equity intraday study announcement](https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html) | Historical retail loss prevalence. Do not relabel as this bot's probability of failure. |
| S16 | [Bailey et al., probability of backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Multiple-testing/CSCV concepts. Repeated strategy searches require explicit accounting. |
| S17 | [Ledoit & Wolf, covariance shrinkage](https://ledoit.net/honey.pdf) | Estimation error and regularized covariance for allocation. Re-estimate inside training folds. |
| S18 | [Rockafellar & Uryasev, general CVaR](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=267256) | Tail-loss/scenario optimization, including discrete loss distributions. |
| S19 | [MoSPI release calendar](https://www.mospi.gov.in/advance-release-calendar) and [methodology FAQ](https://mospi.gov.in/faq) | Official scheduled macro releases and methodology. The dynamic calendar rendered no entries here; no event dates were inferred from that absence. |
| S20 | [Zerodha business disclosure](https://zerodha.com/z-connect/general/business-updates-increased-disclosures-and-improving-transparency) | Historical brokerage business model and separation of pass-through charges from revenue. Not a statement of current revenue percentages. |
| S21 | [DigitalOcean basic VM pricing](https://www.digitalocean.com/pricing/droplets) | Example 1 GiB/1 vCPU US$6 monthly, 2 GiB US$12. Taxes, exchange rate, backup and paid extras excluded; no purchase made. |
| S22 | [Lobo, Fazel & Boyd, fixed transaction costs](https://stanford.edu/~boyd/papers/portfolio.html) | Fixed costs make optimization harder than a plain convex allocation. |
| S23 | [Zerodha static IP](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip) | Static IP required for API orders from 1 April 2026; read/data endpoints can use other IPs. No live orders in this project. |
| S24 | [Kite login documentation](https://kite.trade/docs/connect/v3/user/) | Official login, SHA-256 token exchange, secret boundary and access-token expiry at 06:00 next day. |
| S25 | [Kite rate limits/errors](https://kite.trade/docs/connect/v3/exceptions/) | Quote 1/s and history 3/s; auth/rate errors. Adapter intentionally uses a slower global rate. |
| S26 | [Tailscale Serve examples](https://tailscale.com/docs/reference/examples/serve) | Private HTTPS access to a loopback service. Use Serve, not public Funnel. |
| S27 | [NSE historical data products](https://www.nseindia.com/static/market-data/eod-historical-data-subscription) | Official historical data access; check license, scope and cost before buying. |
| S28 | [NSE corporate data products](https://www.nseindia.com/static/market-data/corporate-data-subscription) | Official corporate-data services exist; comprehensive licensed feeds may be far beyond the hobby budget. |
| S29 | [Hirshleifer & Sheng, macro/micro news](https://www.nber.org/papers/w28931) | Event response depends on information context; avoid fixed universal news weights. |
| S30 | [NSE Budget Sunday circular](https://nsearchives.nseindia.com/content/circulars/CMPT72384.pdf) | 1 February 2026 was a live session; weekday-only scheduling is not an exchange calendar. |

## Acquisition map for the implementation owner

Kite: authenticate, snapshot masters, resolve current symbols/tokens, download bounded price history, and record account observations.

NSE/BSE: obtain security/ISIN maps, corporate-action and trading/settlement calendars, surveillance/eligibility lists, historical membership and original filings. Use official export/download facilities or a licensed provider when automated access is unavailable. Store the original file and its hash.

Company IR: archive annual/quarterly reports and earnings materials with publication evidence, not a current-page scrape pretending to be historical.

News: use RSS for discovery and source spans for extraction. Provider contracts determine retention and redistribution. This package ships no paid news feed and makes no claim of complete news coverage.

Macro: issuer calendars and releases; revisions must remain separate vintages. RBI release schedules should be independently retrieved before use; no RBI meeting dates are hard-coded here.

Research papers: algorithms and failure modes, not directly usable prediction data. Fable must identify exactly which fields its proposed model needs and whether those fields exist before coding it.
