# Implementation contract

These are required behaviors and proposed interfaces. Exact database names may change through a documented design decision.

## Instrument and time

Security identity is ISIN where applicable; an exchange listing has its own exchange, trading symbol, token and effective dates. Preserve delisted and renamed instruments. Historical membership, trading sessions, restrictions and corporate actions are versioned.

Each observation has event time, publisher availability time where known, ingestion time, effective interval and revision/source identifiers. Feature queries use an explicit as-of cutoff. Unknown publication times cannot be silently replaced with midnight.

## Cash and financing ledger

Use auditable journal entries that balance. Model broker cash, settled/unsettled receivables and payables, holdings at cost, financing liability, accrued interest, fees, realized results, deposits and withdrawals. Keep valuation marks distinct from cash flows. Reconcile tax lots and quantity separately from valuation.

Report:

- Net liquidation estimate: cash and valued assets minus liabilities, accrued costs and estimated exit costs, clearly labeled.
- Available cash, reserved cash and broker-reported usable margin separately.
- Realized/unrealized return; contributions/withdrawals excluded from trading profit.
- MTF principal and accrued interest per relevant lot/rule.

Define lot matching, rounding, charge aggregation, effective fee dates and corporate-action treatments before implementing. Compare fixtures against primary broker examples and later against actual statements. A balancing journal can still be economically wrong, so independent expected values are required.

## MTF lifecycle

Proposed states: proposed, eligibility_checked, order_pending, partially_filled, funded, pledge_pending, pledged, margin_shortfall, exit_pending, partially_closed, converted_to_cash, closed, broker_liquidated and reconciliation_required.

Do not imply every state transition is universal; adapt to the verified broker/account workflow. Preserve transitions and timestamps. A pledge instruction does not prove completion. Missing authorisation or eligibility must be visible.

Required inputs: rate schedule, funded amounts, interest day-count/cutoff rules, account product eligibility, security margin/haircut schedule, cash requirements, pledge rules, fee schedule, settlement calendar and corporate actions. Unknown required live inputs fail the entry check.

Interest fixture expectations must be calculated independently. Include weekends, holidays, multiple buys, partial sales, sale day cutoff, cash conversion, rate changes and small-value rounding. Do not assume historical current MTF availability: tag a current-rule replay of older markets as counterfactual.

Maintenance-margin tests include changing security requirements, cash depletion by fees, adverse gaps, unavailable exits and forced broker action. Stop orders are not guaranteed loss limits.

## Evidence schema

Evidence includes source URL/identifier, source type, document hash, publication/ingestion times, subject ISIN, event type, extracted fields, units, source spans, revision link, contradictions and verification status.

Separate extraction confidence from prediction. Numeric facts require units and period. Missing fields stay null. Financial amounts from PDF tables need checks for consolidated/standalone, quarter/year, sign, currency and magnitude.

Only schema-valid approved evidence reaches features. New text never grants a capability or changes the instructions of the service.

## Forecast and allocation

Forecast interface: as-of time, ISIN, horizon, estimated return distribution or clearly labeled score, calibration identifier, sample size, uncertainty, required evidence, expiry, strategy and feature versions.

Order proposal: quantity, side, exchange, financing mode, horizon, limit/price conditions, planned review/exit conditions, costs, maximum intended exposure, reason codes and policy version.

Risk checks include integer share quantities, available cash, unsettled obligations, concentration, correlated exposures, total borrowed principal, financing costs, expected shortfall/scenario loss, turnover, spread/depth, event risks and freshness. Threshold values come from an explicit configuration; example defaults are not optimized facts.

A no-trade decision is a first-class outcome. Overrides cannot bypass invalid credentials, stale critical inputs, reconciliation errors or unavailable broker permissions. A user-approved risk exception must be bounded, expire and be rechecked.

## Execution and recovery

Use a durable intent identifier and transactionally persisted state before submission. Do not assume the broker supports a guaranteed idempotency key. Correlate tags/IDs where supported, reconcile unknown outcomes and avoid blind retries.

Track requested, acknowledged, partially filled, filled, cancelled, rejected and uncertain states. Broker/exchange updates may duplicate, arrive late or out of order. Fill IDs and cumulative quantities must prevent duplicate accounting.

One active writer submits orders. Use a lease/fencing design and test split-brain/restart behavior. A restarted process reconciles broker state before new orders. Persist cancellation attempts separately from confirmed cancellations.

Read-only broker integration must technically block order methods, not just hide buttons. Separate replay, paper, read-only and live credentials/configurations. No secrets in the phone package.

## Audit and explanatory interface

Every decision links input snapshot IDs, feature values, forecast version, proposed allocation, cost estimate, risk-check outputs, final decision, order/fill IDs and ledger entries. Preserve competing proposals and rejection reason codes.

Provide a deterministic renderer for every reason code with unit-aware values and explicit unknowns. Never present a score as a probability without a calibration record.

Separate immutable business events from rotating diagnostic logs. Include redaction tests, backup restoration tests and storage quotas. A failure review bundle contains a minimal synthetic/redacted replay, expected/actual behavior, versions and relevant logs.

## Operations

Run optional research with a worker/time/memory budget separate from operational risk processing. At an AI spending limit stop new optional requests, not broker reconciliation. Alert for stale data, expired auth, margin headroom, unknown orders, ledger disagreement, worker failure and backup failure.

Emergency controls are distinct: pause new entries; request cancellation of pending entries; manage existing exposure through reviewed policy; open the broker's own app. Never describe a kill switch as guaranteed immediate liquidation.
