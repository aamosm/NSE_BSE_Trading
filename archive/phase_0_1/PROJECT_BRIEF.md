# Project brief

## Goal

A personal Indian equities application for research, historical replay, paper trading and eventual controlled execution on NSE/BSE. Starting capital assumption is ₹10,000, separate from development and infrastructure spending. The intended operating style is part-time oversight, with the final feasible strategy scope determined by evidence.

## Required from the foundation

- Both fully paid holdings and MTF: liabilities, interest, pledges, maintenance margin, liquidation and reconciliation.
- Multiple holding horizons with a shared portfolio/risk budget.
- Price/financial features and timestamped text/event evidence.
- Deterministic execution and hard risk rules; validated, frozen statistical forecasts are permitted.
- LLM extraction with provenance; no LLM trading authority.
- Complete decision and accounting audit trail, including no-trade decisions.
- Manual trade reconciliation at the connected broker and explicit imports/adapters for other brokers.
- Meaningful historical tests, an initial registry of 1,200 functional scenarios and 1,000 research configurations.
- Controlled offline improvement with release history and independent review.
- Phone dashboard with explanations generated from recorded numbers and reason codes.
- Hosted paper operation, then an Android package and a possible limited live release.

## Initial scope

One user, one execution broker, a bounded liquid equities research universe, no derivatives. Model NSE/BSE venues by exchange instrument and shared ISIN. Cross-exchange spread capture is an optional research strategy; it cannot bypass settlement, inventory or execution constraints.

MTF simulation is mandatory from Phase 1. Live trading and live borrowing are off until their release criteria and user-selected budgets are satisfied. That is an activation boundary, not deferred MTF design.

## Non-negotiable economic reporting

Separate equity from buying power; costs from returns; realized from unrealized gains; portfolio performance from infrastructure spending. No guaranteed profits or fixed withdrawal funded by borrowing. Compare active strategies with simple baselines.

## Decisions still to be made

Machine/runtime versions; chosen broker account and product availability; licensed data coverage; actual runtime API model based on extraction evaluation; infrastructure budget; tolerable rupee losses; live exposure/financing caps; retention and backup policy. Record unknowns rather than inventing approvals.

## Current state

Specification kit only. No application implementation or strategy results exist yet.
