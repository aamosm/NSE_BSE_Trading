# Phase prompts

Use one prompt at a time after the preceding phase has appropriate evidence and review. The implementation owner must read AGENTS.md and docs/HANDOFF.md for each phase. These prompts authorize scoped local implementation; real credentials, purchases, deployment and live activation require their own concrete configuration and user action.

## Phase 1 — Cash and MTF accounting

Implement the domain and accounting foundation from docs/IMPLEMENTATION_CONTRACT.md and the reviewed Phase 1 plan. Use explicit decimal/rounding rules, effective-dated costs and a balanced ledger. Model cash and MTF lots, funding liability, accrued interest, pledge lifecycle, margin headroom, partial exits, conversion to cash and forced-exit accounting. Do not use a leverage multiplier as a substitute for financing accounting.

Create independent hand-worked fixtures for a normal cash trade, a funded trade across a weekend, several purchase lots with a partial exit, a margin change and a corporate action. Use the broker's verified rules and label unresolved assumptions. Add meaningful invariant/property tests. Finish with a replayable accounting demonstration, actual test output and a handoff. No broker connection.

## Phase 2 — Point-in-time data and evidence

Implement a small permitted or synthetic ingestion pipeline with instrument identity, exchange listings, publication/ingestion timestamps, revisions and corporate actions. Start with structured sources before adding text extraction. Build source hashes, deduplication, availability cutoffs and quality checks.

Define a strict extraction schema for text, including source spans and units. Use a fake extractor for local tests. If a runtime model is later configured, evaluate it against hand-labeled examples before accepting it. Treat source instructions as untrusted. Store source reliability separately from prediction confidence. Do not claim historical coverage you do not possess. Update the data inventory and handoff.

## Phase 3 — Replay and simulated execution

Implement a deterministic replay clock and simulated broker with the same order interface planned for live use. Model spreads/slippage, partial fills, rejections, uncertain acknowledgement, duplicate and out-of-order events, cancellations, settlement and MTF state. Historical candles cannot establish exact queue position; conservative fill assumptions must be explicit.

Persist intents before submission and use recoverable state transitions. Prove that a simulated lost acknowledgement or restart cannot blindly create another order. Produce a local end-to-end cash/MTF demonstration with a ledger and decision explanation. Keep real broker order methods unavailable.

## Phase 4 — Forecasts, allocator and risk

Implement strategy interfaces for fundamental/valuation, momentum and event/analogue research. Start with transparent feature definitions and simple baselines. Keep frozen model/feature versions and do not mislabel scores as calibrated probabilities.

Implement integer-share allocation across horizons and an explicit cash alternative. Include rupee transaction costs, financing costs, uncertainty, correlation/concentration, liquidity and stressed loss. Integrate MTF as a financing choice constrained by the same total portfolio budget and a separate borrowing cap. Compare with cash-only behavior.

Implement deterministic reason codes and tests where changing fees, evidence freshness, cash or margin appropriately changes the decision. Live limits remain unset. Do not promise profitability.

## Phase 5 — Scenario and research harness

Turn experiments/coverage_matrix_1200.json into meaningful fixtures and assertions. Report planned/implemented/executed/passed/failed/skipped separately; a registry row alone is not a test. Add cases needed beyond the matrix.

Implement a bounded runner for experiments/research_trials_1000.json. Verify ten varied candidates first. Use cached point-in-time inputs, chronological splits, purging/embargo appropriate to overlapping targets and an untouched final evaluation. Record all trials, costs, financing rules and counterfactual assumptions. Mark unsupported data/horizons NOT_EVALUABLE.

Produce a baseline comparison, multiple-testing assessment, parameter stability, drawdowns, turnover, financing cost and uncertainty. Include source/LLM hindsight leakage limitations. Do not use paid model calls for every simulation.

## Phase 6 — Phone dashboard

Build a responsive React/TypeScript dashboard from actual backend state. Show net equity, funded principal, cash/reserves, realized/unrealized P&L, accrued interest, margin headroom, holdings by horizon, orders, source freshness, authentication, API spending and strategy version.

Build deterministic explanations from stored reason codes and numbers. Show unknowns and stale state explicitly. Include views for rejected trades, manual activity and audit replay. No LLM narration endpoint. Start with paper/read-only operation. Test the few important data/state transitions, including offline/stale viewing.

## Phase 7 — Broker read-only integration

Implement the selected broker adapter with order submission technically disabled. Use official login and server-side token storage; give the user clear local instructions for supplying credentials without placing them in chat or Git.

Import holdings, positions, funds, daily trades and relevant order updates. Reconcile manual orders and recover missed events. Support statement imports for prior history and explicitly separate other brokers. Validate MTF eligibility/margin/statement data and record gaps. Unknown states block new proposals from becoming executable. Do not place an order to test this phase.

## Phase 8 — Hosted paper service

Prepare a Docker Compose deployment, persistence, private database access, authenticated frontend, HTTPS/private-network route, budget controls, operational alerts, backup/restore and one active execution-worker design. Use a stable outbound IP compatible with current broker requirements.

Test restart, restoration, stale data, credential expiry and failed model calls locally first. Produce exact deployment instructions and a current cost estimate. If a host/account has been authorized, deploy in paper mode only and verify the actual service. Otherwise leave a reviewable deployment package and state the one needed account action. Do not describe prepared files as a running deployment.

## Phase 9 — Android package

Wrap the working phone interface with Capacitor. Configure authenticated backend access, appropriate notifications, secure local session handling and explicit stale/offline behavior. The server remains the trading engine; no broker or model secrets go in the APK.

Build a personal-use signed APK through the installed Android toolchain, keeping signing material private. Verify on an emulator and the user's phone where available. Clearly distinguish built, emulator-tested and physically tested status. A public store release is outside this phase.

## Phase 10 — Limited live release preparation

Prepare a release candidate only if accounting/execution tests, source rules, reconciliation and forward paper evidence support it. Review applicable broker/exchange retail-algo rules, product permissions, static IP, authentication and MTF workflow for this account.

Produce a release report containing unresolved defects, selected strategy evidence, expected costs, monitoring requirements, exact user-selected loss/exposure/borrowing caps, disable/recovery procedure and separate cash/MTF activation settings.

A live-mode switch must reject missing limits or unresolved critical states. Do not equate a review report with permission to trade. Live activation requires the user's explicit configured scope and a functioning monitoring/reconciliation path. Record actual fills and cost deviations after activation; preserve an immediate way to pause new entries.
