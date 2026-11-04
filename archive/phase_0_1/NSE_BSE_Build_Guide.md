# Build guide: a personal NSE/BSE research and trading system

Prepared 3 November 2026. Starting portfolio assumption: ₹10,000. Personal use, Indian cash equities, cash delivery and MTF. This is a project plan and implementation specification, not a functioning trading application or a claim of profitable results. Product details below are a dated snapshot; recheck them before activation.

## 1. What we are building

Build an application that collects reliable evidence, estimates opportunities over several holding periods, allocates capital under explicit constraints, simulates and records every decision, and eventually executes through a broker. It must understand MTF from its first accounting and simulation modules.

There are three separate achievements:

1. A correct, observable application: achievable with the tools you have, careful review and testing.
2. A strategy that earns more than its trading and financing costs: a research question. More features, better coding models and more tests do not settle it.
3. Enough profit to pay for hosting, data, AI and withdrawals from ₹10,000: a much harder financial target. Treat initial development costs as a separate project budget.

Strong models can help build almost every component. They cannot supply trustworthy historical data that you do not have, certify their own correctness, or guarantee an investment edge. Build the ability to measure the edge before increasing capital.

MTF belongs in the initial domain model, simulator, portfolio allocator, risk engine, logs, dashboard and broker interface. Start it in replay/paper mode. Activating real borrowing later is a configuration and release decision, not an architectural retrofit.

## 2. Who does what

The following is a proposed division of responsibility, not a benchmark showing one model always wins.

| Participant | Main responsibility | Output |
| --- | --- | --- |
| You | Choose budgets and tolerable losses; review releases; perform broker authentication | Written settings and release decisions |
| GPT-6 Astra, when available in your plan | Architecture, statistical design, adversarial review of accounting and tests | Specifications, counterexamples, review findings |
| Claude Sonnet 5.5 in Claude Code, or the capable coding model available in your plan | Main implementation owner | Small code changes, tests, documentation and handoffs |
| Claude Fable 5.1 through paid access if needed | Difficult mathematical design and review: MTF ledger, allocation objective, leakage, confusing failures | Bounded specification or review; proposed corrections with evidence |
| Codex/Sol, if available | Optional independent code/test review or temporary implementation owner | Review report or isolated change |
| Ordinary Python programs | Run simulations, calculate features, check invariants, compare experiments | Reproducible results |
| Small runtime model, evaluated before selection | Extract structured facts from approved text sources | Schema-validated facts with source references |

Use one implementation owner at a time. Two models editing the same files can create subtle inconsistencies. Start with Claude writing, GPT reviewing, and Fable reviewing only high-value uncertainties. A reviewer may write its review document but should not silently change production code. Transfer ownership explicitly if you want another model to implement a fix.

Models share work through a private Git repository and files, not through an elaborate autonomous agent network. Each session reads PROJECT_BRIEF.md, AGENTS.md, the current task and docs/HANDOFF.md. Each session leaves a handoff with the commit, changes, exact checks, unresolved issues and next task.

Your chats do not permanently train the foundation model. Persistent project documents, a hypothesis registry, test fixtures and versioned statistical models are the practical memory.

## 3. Connect the subscriptions correctly

Claude Pro includes Claude Code with shared plan limits. Install the official Claude Code VS Code extension, sign in with your Claude subscription, and check the active model and account. In the terminal version, /model and /status help inspect configuration. An existing ANTHROPIC_API_KEY environment variable can switch usage to API billing: check whether one exists without printing its value. Do not assume Fable is included in Pro; verify availability and billing before selecting it. [S1, S2]

Codex supports ChatGPT sign-in and API-key authentication as separate routes. Use ChatGPT sign-in for included development usage. Model access and limits depend on your account; use Astra for difficult reviews if available and the coding model available to you for routine work. [S3, S4]

The running trading application needs its own API credentials and budget if it calls a model. It does not automatically receive unlimited API usage from your chat subscriptions. Do not automate a consumer chat session with stored cookies to operate the service.

Do not buy another subscription at the beginning. First complete the foundation with the plans you already have. If Fable API access is useful, approve a small milestone budget, such as US$5–10, and stop at the cap.

For a paid Fable review, first check whether your Claude account already offers it. Otherwise use an Anthropic API project with a separate budget and a supported review interface, such as the Console Workbench if available to your account. Provide only the relevant specification, redacted code, failing fixture and FABLE_REVIEW.txt. If you use Claude Code with API billing, keep that session's credentials isolated and verify the billing mode before returning to subscription work. Do not set a paid API key globally just to perform one review.

At the algorithm-design milestone, Fable can draft the mathematical specification and counterexamples; GPT independently challenges it; Claude implements the accepted specification. This uses the expensive model where its contribution can be inspected.

## 4. Begin on your computer

The example workflow assumes Windows and VS Code; the architecture also works on macOS or Linux.

1. Extract the starter ZIP into a new project folder, for example C:\Projects\MarketLab. Keep it separate from unrelated projects.
2. Open that extracted folder in VS Code. Read README_FIRST.md.
3. Use the official Claude Code extension and sign in with your existing Claude account. Use Sonnet or the capable coding model your plan exposes.
4. If you use Codex locally, install the official extension and choose ChatGPT sign-in. Only one tool edits the implementation at a time.
5. Open prompts/00_START_HERE.txt and paste its contents into Claude Code. It requests a scoped environment check and Phase 0 only.
6. Review the resulting docs/ENVIRONMENT.md and docs/HANDOFF.md. Let the implementation owner give installation commands appropriate to the detected machine. Do not blindly run commands copied from an unverified tutorial.
7. Create a local Git repository after the secret exclusions are in place. Make the first commit. A private GitHub remote is useful for history and review; it is not required for the first local milestone.
8. Give the handoff and relevant files to GPT for a review using prompts/REVIEW.txt. Resolve material findings before moving to Phase 1.

Phase 0 needs no broker credentials, API purchases, cloud server or live money. The kit provides specifications and planned test registries. It does not contain the finished application.

## 5. Learn the rules before collecting trading opinions

Start with a short, bounded research sprint. The purpose is to create a reliable rulebook and identify missing data, not to make an AI consume the entire internet.

First study broker API documentation, the broker's MTF terms, official exchange announcements, trading calendars, settlement and product rules. For every rule store its source, effective date, last check, affected products and unresolved ambiguities. Account-specific behavior must be verified against your own broker configuration.

Next read focused educational material on financial statements, market microstructure, corporate actions, portfolio risk and statistical validation. Tutorials, newsletters and videos are useful for generating hypotheses. Use provided or permitted transcripts; do not bypass paywalls or assume an entire video library can be copied and redistributed.

For each useful claim, create a record:

| Field | Example |
| --- | --- |
| Claim | A positive earnings surprise may predict subsequent returns |
| Definition | Actual versus a timestamped, pre-release expectation |
| Available information | Filing and expectations published before the decision |
| Counterexample | Good reported growth but weak guidance or an already expensive valuation |
| Proposed test | Compare against sector/market performance after all costs |
| Evidence status | Untested, rejected, inconclusive or provisionally supported |

A magazine recommendation is an opinion. Two articles repeating the same press release are one underlying source. Two models agreeing are not independent factual confirmation. Prefer the original filing plus an independently checkable number, source or reconciliation.

Initially limit the research universe to roughly 20–30 liquid securities and a small number of strategy families. Use historically correct eligibility and constituents when backtesting. Current winners are a biased historical universe.

No model can enumerate every market variable: some information, expectations and future actions are unobservable. Maintain a factor register with an evidence source, rationale, measurement, cost and incremental test for each addition. Remove features that add complexity without stable out-of-sample benefit.

## 6. The architecture

Use a modular application with one controlled execution process. Avoid a swarm of services until there is a demonstrated need.

| Component | Suggested implementation | Responsibility |
| --- | --- | --- |
| Backend | Python, FastAPI, Pydantic | Authenticated application API and validated interfaces |
| Accounting store | PostgreSQL, SQLAlchemy, Alembic | Orders, fills, cash, borrowings, decisions and migrations |
| Research storage | Parquet and DuckDB | Historical features and inexpensive batch analysis |
| Calculations | NumPy/pandas; statistical libraries as justified | Features, forecasts, costs, allocation |
| Verification | pytest and property-based tests | Examples, accounting invariants and failure cases |
| Web/phone interface | React and TypeScript | Dashboard and deterministic explanations |
| Android application | Capacitor wrapper around the web interface | Installable app, authentication and notifications |
| Deployment | Docker Compose on one small Linux server | Reproducible services, persistence and restart |

Pin compatible package versions during implementation and commit lockfiles. These are proposed tools, not an already-tested dependency set.

Maintain explicit boundaries:

1. Source adapters collect permitted material and record timestamps.
2. An extraction service converts text into typed evidence.
3. Feature code combines evidence with point-in-time price and financial data.
4. Frozen, versioned strategy code or statistical models produce forecasts by horizon.
5. The allocator proposes positions and cash reserves.
6. The risk engine may reduce or reject proposals.
7. The execution engine manages order states and reconciliation.
8. The ledger and audit trail feed the phone dashboard and research review.

The LLM has no broker credentials, shell tools or authority to change risk settings. Web pages and newsletters are untrusted data, including any instructions embedded inside them. Validate JSON against a strict schema and reject unsupported claims.

Keep the same strategy, fee and risk interfaces for replay, paper and live modes. The execution adapter and clock differ. All timestamps must be timezone-aware; display India time while retaining unambiguous stored timestamps.

## 7. MTF from the first implementation

Treat financing as part of a position's lifecycle. A cash position and an MTF position can share a security but have different liabilities, restrictions and costs.

A position lot needs quantities, purchase time, exchange, settlement status, cash contribution, funded principal, accrued interest, pledge state, eligibility snapshot, margin requirement, charges and realized results. A single Boolean named leveraged is insufficient.

As checked on 3 November 2026, Zerodha lists MTF interest at 0.04% per day on the funded balance from T+1, brokerage of 0.3% or ₹20 per execution, whichever is lower, and pledge/unpledge charges. Model the detailed charging units rather than assuming one fee per round trip. [S5]

For scale, ₹5,000 funded for 30 chargeable days costs ₹60 in interest alone at that rate. This arithmetic is not a forecast of profit or the exact statement for every settlement situation. Interest and other charges can consume a small trade's expected advantage.

Eligibility and margins can change, and the broker can require additional cash or liquidate positions under its terms. Store versioned rules rather than a universal leverage multiplier. Verify the pledge/authorization workflow for your account; documentation and account arrangements can differ. Unknown eligibility or an unresolved margin state blocks new funded entries. [S6]

Implement and test:

- Opening, partial fills, partial exits and multiple purchase lots.
- Interest across weekends and holidays, rounding, effective rates and sale/conversion cutoff.
- Pledging, authorization pending, failure and unpledging.
- Maintenance margin changes, adverse price moves and funding headroom.
- Conversion to cash holdings, settlement and corporate actions.
- Broker liquidation, gaps, price circuits and unavailable liquidity.
- Reconciliation of the app's liability, cash and charges against broker statements.

Calculate portfolio equity after subtracting financing liabilities and accrued costs. Borrowed cash is not income. Buying power is not profit.

Run every candidate with a cash-only comparator. Permit MTF only when the incremental expected benefit clears financing costs, model uncertainty and stress constraints. The live caps must be deliberately configured; the example policy leaves them unset and live execution disabled.

## 8. Make the decision logic precise

Begin with three research families: fundamental/quality and valuation for longer horizons; price/volume or momentum for shorter horizons; and documented event reactions. Add historical analogues as a feature whose contribution must be measured.

For an event, encode what happened, when it became known, expectations where available, magnitude, company/sector context, valuation, preceding returns, liquidity and wider conditions. Retrieve comparable past events using only information known at the historical decision time. Report sample size and differences; a convincing story with three analogues is not strong statistical evidence.

Keep these quantities distinct:

- Extraction reliability: did the system correctly read the source?
- Source quality: how credible and timely is the underlying information?
- Forecast probability: how often do similarly scored predictions succeed out of sample?
- Expected net payoff: what are the sizes and probabilities of gains and losses after costs?

An LLM's statement of 95% confidence is not a measured 95% chance of stock appreciation. Calibrate forecast probabilities on held-out observations. If no reliable calibration exists, display unknown.

A proposed allocation objective is expected net portfolio return minus penalties for downside loss, concentration, turnover and illiquidity. Estimate costs in rupees for the actual integer share quantities. Include cash, settlement, fees, funding, exposure and liquidity constraints. Stress results against estimation errors rather than optimizing one fragile point forecast.

Cash is a valid allocation. The long-term, short-term and event sleeves are allowed to remain empty. At ₹10,000, integer shares and fixed charges limit practical diversification; ten tiny positions can be less efficient than a few measured exposures. Do not force allocation percentages because a diagram looks diversified.

Use a strict MTF sub-budget within the total portfolio risk budget. More accumulated equity may allow larger rupee positions at the same risk fraction; it does not automatically justify a larger risk fraction.

Track possible withdrawals separately. A proposed rule is to reserve a user-selected fraction of realized gains after costs and a tax reserve, subject to settled cash and margin headroom. Start with no automatic transfer. ₹50 every week equals ₹2,600 a year, or 26% of the initial ₹10,000, before ongoing costs; a fixed payout may withdraw principal.

NSE and BSE listings of the same ISIN are the same underlying equity exposure, not diversification. Route using executable bid/ask quotes, depth, costs, settlement and the broker's allowed workflow. Treat cross-exchange spread capture as a separate hypothesis. A ₹1 difference between last traded prices is not an executable profit. Never simulate both legs as guaranteed simultaneous fills or assume unmatched intraday legs cancel across exchanges.

## 9. Extreme logging that remains useful

Record enough to reproduce a decision; do not fill disks with irrelevant text.

Each decision receives a unique trace ID linking source versions, extracted facts, feature values, forecast version, proposed quantity, financing choice, cost estimate, risk checks, order intent, broker updates, fills and final accounting. Log rejected opportunities and reasons for doing nothing as well as trades.

Record software commit, model/prompt identifiers, dataset hashes, effective policy version and input cutoff. Preserve original events; corrections are new events. Store money as decimal values or integer minor units, never binary floating point in accounting.

Use append-only audit events plus a reconciled ledger. An order acknowledgement is not a fill. A timeout is not proof that an order failed. Recover by checking broker state, and prevent duplicate intents. Broker order history is not a substitute for your own durable history. [S7]

Manual orders at the same broker must be reconciled too. Kite's user WebSocket order updates include activity through its other platforms; the app-specific webhook covers only orders placed through that API key. Use snapshots and statement imports to recover missed history. Other brokers require their own authorized connection or import. Unreconciled external activity reduces available risk capacity and may block new orders. [S8]

For the phone, generate text from reason codes and values:

“No purchase: estimated advantage ₹18 is below estimated costs ₹24.”

“MTF rejected: simulated adverse move leaves ₹X less than the required cash buffer.”

“Research unavailable: the earnings announcement could not be verified.”

These are templates, not LLM explanations. Display ranges and uncertainty when the underlying quantities are estimates. The dashboard should explain recorded factors, not invent an internal thought process.

Keep financial events and reproducibility metadata durably under a defined retention policy. Rotate debug logs; place explicit limits on tick/raw-document storage in accordance with data terms. Back up the ledger and test restoration. Exclude API keys, tokens, OTPs and sensitive authentication URLs from logs, prompts and review bundles.

## 10. Your 1,000-plus tests: two different programs

The kit contains two generated registries. They are definitions to implement and run, not completed backtests or proof of correctness.

### A. 1,200 functional scenario definitions

10 scenario families × 5 market contexts × 4 portfolio states × 3 liquidity levels × 2 financing modes.

The families include normal execution, partial fills, uncertain order acknowledgement, duplicate/reordered updates, stale data, corporate actions, manual trades, financing lifecycle, margin changes and gap/circuit/forced-exit behavior.

Each definition needs a fixture, expected accounting and explicit assertions. Cash-mode financing cases should verify that prohibited funding operations are rejected or absent. Some combinations intentionally expect no trade. Do not discard hard cases just to obtain a green count.

Add hand-calculated examples, property-based tests and outage/recovery integration tests. Validate ledger balance, no double counting, no order from invalid data, no spend of reserved cash, no risk bypass and no duplication after restart.

### B. 1,000 research candidate configurations

An illustrative preregistered grid contains 5 event weights × 5 momentum weights × 4 analogue-history windows × 5 holding horizons × 2 financing policies.

The registry includes a fixed fundamental component and normalized weights. The grid is deliberately understandable. The number 1,000 is a coverage budget, not a reason to invent 1,000 unrelated rules.

First verify ten candidates end to end. Then run the full grid with cached inputs, bounded workers and deterministic seeds. A normal program does the repeated calculation. Fable and GPT review designs and summaries; they do not need to be called for every simulation.

### Prevent historical hindsight

Use information as it was available then: filing publication times, revisions, delistings, historical constituents and corporate actions. Today's revised fundamentals must not appear in yesterday's decision. Historical candles alone do not provide this complete dataset. [S9]

A modern LLM may know an old company's later outcome from pretraining. Supplying an old date does not erase that knowledge. Historical text extraction must be restricted to supplied documents, with no free-form prediction from remembered history; mask identifiers where useful and audit source grounding. Even these controls do not prove absence of leakage. Forward paper performance remains necessary.

Split time chronologically into development, validation and a final untouched evaluation period. Fit transformations on development data only. Purge overlapping outcome windows around splits and choose embargo intervals appropriate to the holding horizon. A one-year target needs much longer data than a one-day target.

Keep a registry of every experiment, including failures. Repeatedly selecting the best of many trials increases overfitting risk; ordinary train/test splitting does not erase strategy-selection bias. Add a suitable multiple-testing analysis, such as probability-of-backtest-overfitting or a justified alternative, under statistical review. [S10]

Compare against simple investable baselines with the same capital, data, costs and financing assumptions. Report returns, drawdowns, tail losses, turnover, exposure, costs, interest, sample size, regime stability and uncertainty. Stress spreads, slippage, delayed data and failed fills. Do not call a result an improvement because only gross return rose.

## 11. How it improves without rewriting itself live

Use a controlled research loop:

1. Freeze a release and its configuration.
2. Collect decisions, execution outcomes and accounting discrepancies.
3. Classify issues: data defect, software defect, execution mismatch, forecast error, or ordinary uncertainty.
4. Give a redacted, reproducible failure bundle to the reviewing model.
5. Propose one specific change with an expected effect and a way to falsify it.
6. Have the implementation owner make the change on a branch.
7. Rerun affected correctness tests and the predefined research evaluation.
8. Compare the challenger with the current release; promote only when the evidence supports it.

Do not relax limits to explain away a losing trade. Do not repeatedly retune on a supposedly untouched test set. A profitable trade can come from a bad decision and a losing trade can come from a well-supported decision.

Your rejection of a proposed exception is a preference constraint, not a market label proving the stock was bad. Store the decision and stop asking again for the same unchanged request. The interface may show an evidence brief but must not pressure you to accept more risk.

## 12. Build and acceptance sequence

| Phase | Deliverable | Minimum evidence before moving on |
| --- | --- | --- |
| 0 | Environment, rules register, dependency decisions, repository | Reproducible setup; unknowns explicit |
| 1 | Cash and MTF domain, ledger and cost model | Hand-worked fixtures and accounting invariants agree |
| 2 | Historical data and evidence ingestion | Source lineage, availability timestamps and revision handling |
| 3 | Replay/paper engine and broker simulator | Partial fill, timeout, duplicate and restart cases pass |
| 4 | Strategy interfaces, forecasts, allocation and risk | Costs, uncertainty and MTF constraints change decisions correctly |
| 5 | Research harness and scenario suite | Honest 1,200-scenario coverage report; 1,000-trial report when data supports it |
| 6 | Phone web dashboard and explanations | Ledger-derived totals, stale-state warnings, useful logs |
| 7 | Broker read-only integration and reconciliation | Manual trades, missing events and daily state recovered |
| 8 | Hosted paper service | Restart, backup restoration, monitoring and authentication tested |
| 9 | Android package | Phone authentication, notifications and offline handling verified |
| 10 | Limited live release, if justified | Explicit budget/configuration; reviewed execution and MTF evidence |

Use prompts/PHASE_PROMPTS.md one phase at a time. Each phase can contain several small commits. A beginner should expect multiple weeks to months of intermittent work, depending heavily on data availability and review quality. Running 1,000 jobs overnight does not shorten the calendar time needed to observe live behavior.

An initial 4–8 weeks of forward paper operation is an operational shakedown, not proof of profitability, especially for long holding periods. Long-term strategies cannot be validated with a month of observations.

## 13. Hosting, schedule and Android

Develop locally first. For hosting, choose a small Linux server with persistent storage and a stable outbound IP, run the backend/database with Docker Compose, and build the frontend before deployment. Run large research batches locally or in a separately budgeted job so they cannot starve the trading process.

Use one active execution worker with a lease/fencing mechanism. Recovery must reconcile orders before resuming. Keep application health monitoring independent enough to alert when the application itself fails. Protect the dashboard with authentication and HTTPS or a suitable private network. Keep database ports private.

Zerodha requires a registered static IP for API order placement from 1 April 2026; its dedicated guidance distinguishes order placement from other API traffic. Plan the hosting around that before live activation. [S11]

Kite access tokens ordinarily expire at 6 a.m. the next day and can be invalidated earlier. Build a visible reauthentication flow and suspend new orders when credentials are invalid. Do not promise a permanently unattended login or store a TOTP seed to bypass interactive authentication. [S12]

An example low-frequency operating schedule in India time:

| Time/event | Work |
| --- | --- |
| 08:00–08:45 on trading days | Overnight sources, calendar, data health and portfolio review |
| Before first planned order | Authenticate, reconcile, verify current margin and permissions |
| During relevant market sessions | Broker events, risk and data freshness; bounded checks for held/watched securities |
| After market close | Fills, charges, cash and portfolio reconciliation |
| Around 20:30 | New filings and next-session research |
| Weekend budgeted window | Research batch and one consolidated review report |

Read the actual exchange/security session calendar rather than hardcoding universal hours. MTF monitoring must respond to relevant price/margin changes while exposure exists. Intraday operation brings more supervision and outage sensitivity than a low-frequency portfolio.

Start the phone interface as a responsive web app. Then use Capacitor to package the same interface for Android, avoiding a second business-logic implementation. The trading engine stays on the server. The phone displays status, evidence, costs and controls; Android background execution is not the trading scheduler. [S13]

Build a signed APK locally for personal use; a public store listing is a separate project. Never put broker or model API secrets in the APK. An approval must expire and be revalidated against fresh prices, cash, holdings and policy before it can lead to an order. Offline mode is viewing only.

The main dashboard needs equity versus borrowed principal, realized/unrealized results, accrued interest, free/reserved cash, maintenance-margin headroom, positions by horizon, pending orders, data freshness, authentication status, research version, API spending and an emergency pause. Pausing entries does not itself close existing positions.

## 14. Costs and what is worth paying for

Use separate budgets for portfolio capital, development and recurring operation.

| Item | Starting approach |
| --- | --- |
| Development models | Existing subscriptions; no automatic upgrade |
| Fable reviews | Optional capped milestone spend |
| Early replay/paper | Local computer and permitted fixtures/data |
| Broker API | Choose when live data/integration is needed |
| Runtime text extraction | Small evaluated model with per-request and monthly limits |
| Hosting | Start when local paper operation is stable |
| Historical point-in-time data | Investigate coverage/licensing; cost may dominate |

Zerodha currently offers free personal APIs for order/portfolio operations and ₹500/month Connect access with streaming and historical candle data. The latter is useful if you choose Zerodha, but it does not provide all historical news, expectations, filings or research-ready point-in-time fundamentals. [S14]

Prefer one broker adapter initially. A second independently sourced data check can be useful; adding several broker execution integrations before reconciliation works increases failure modes. A cheaper API should be evaluated together with brokerage, data quality, supported products and operational requirements.

Current listed Claude API base prices include Fable 5.1 at US$10 per million input tokens and US$50 per million output tokens. A 100,000-input/10,000-output-token review therefore costs US$1.50 in base token charges; repeated tool loops and extra billed tokens increase the total. Haiku 5.5 lists US$0.10/US$0.50 per million for prompts within its lower context tier. Measure actual extraction quality before choosing it. [S15]

A narrowly scoped workload of 200 new documents/day, each averaging 1,500 input and 200 output tokens, would use 9 million input and 1.2 million output tokens in 30 days: about US$1.50 at those Haiku rates, before retrieval/search, retries, tax or other charges. This is an arithmetic example, not a quote for comprehensive market research. Cache by document hash and extract only changed, relevant material.

One hosting reference is the Lightsail Linux public-IPv4 tier around US$12/month with 2 GB memory; confirm region, taxes, storage, backup and actual workload before buying. It is a possible small operational server, not a promised capacity for all historical experiments. [S16]

Even ₹500/month alone is ₹6,000/year, or 60% of ₹10,000. If all recurring costs were ₹2,000/month, they would total ₹24,000/year before a withdrawal. These examples explain why ₹10,000 is suitable as a learning/pilot account but cannot be assumed to fund this infrastructure from profits.

Set an internal request budget as well as provider billing limits. At the cap, stop optional extraction and research; keep risk controls and reconciliation functioning. Do not trade on stale research merely because the AI budget ran out.

## 15. Reuse existing work deliberately

Review Microsoft Qlib for dataset/research organization and point-in-time handling, and broker SDKs for supported API calls. OpenAlgo may be worth evaluating as an integration reference. Their presence does not establish that they cover your MTF accounting, India-specific data or operational risks. [S9, S17]

Before adopting any project, record the exact version, license, maintained features, dependencies, known issues and the parts you will use. Read unfamiliar order-placement code before granting credentials. Add adapter contract tests around adopted components.

Start with borrowed ideas and well-understood modules. Avoid forking a large trading platform wholesale merely because its demo looks complete.

## 16. Definition of a successful first milestone

The first useful result is a local demonstration that imports a small permitted or synthetic dataset, simulates both cash and MTF, produces a balanced ledger and explains a rejected or accepted simulated trade. It should survive a duplicate event and restart without creating another trade.

That result gives the later research a trustworthy foundation. A large dashboard connected to an unverified balance calculation does not.

The immediate action is prompts/00_START_HERE.txt. Do Phase 0, get its handoff reviewed, and then implement Phase 1. Keep the larger goal visible while limiting each coding session to one verifiable piece.

## Primary sources

These are starting references reviewed on 3 November 2026 where accessible. The BSE page returned an access error and is listed as an official starting location, not as verified API access. Account entitlements, fees and rules must be refreshed when implemented.

- S1: [Claude Code and subscription authentication](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan)
- S2: [Claude Code model configuration](https://support.claude.com/en/articles/11940350-claude-code-model-configuration)
- S3: [Codex authentication](https://learn.chatgpt.com/docs/auth)
- S4: [Codex models](https://learn.chatgpt.com/docs/models)
- S5: [Zerodha MTF FAQ](https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/margin-trading-facility-mtf-faqs)
- S6: [Zerodha MTF terms](https://zerodha.com/tos/mtf)
- S7: [Kite order API](https://kite.trade/docs/connect/v3/orders/)
- S8: [Kite postbacks and user order updates](https://kite.trade/docs/connect/v3/postbacks/)
- S9: [Qlib point-in-time data documentation](https://github.com/microsoft/qlib/blob/main/docs/advanced/PIT.rst)
- S10: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
- S11: [Zerodha static IP requirements](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip)
- S12: [Kite login and token documentation](https://kite.trade/docs/connect/v3/user/)
- S13: [Capacitor documentation](https://capacitorjs.com/docs)
- S14: [Zerodha API products and prices](https://zerodha.com/products/api/)
- S15: [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- S16: [Lightsail pricing](https://aws.amazon.com/lightsail/pricing/)
- S17: [OpenAlgo repository](https://github.com/marketcalls/openalgo)
- S18: [NSE official feeds](https://www.nseindia.com/static/rss-feed)
- S19: [BSE corporate announcements](https://www.bseindia.com/corporates/ann.html)
- S20: [FastAPI documentation](https://fastapi.tiangolo.com/)
- S21: [Docker Compose documentation](https://docs.docker.com/compose/)
- S22: [Zerodha MTF ledger entries](https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/mtf-funds-statement-entries)
