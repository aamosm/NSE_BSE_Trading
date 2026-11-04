# Active implementation contract

This replaces the archived contract. MTF is removed, and the authorized broker integration is read-only.

## Separation of responsibilities

The collector owns broker credentials and writes observations. Offline researchers read redacted/exported data. Future forecasting workers receive validated features, not tokens. A future paper coordinator may consume signed/versioned forecasts; no broker order gateway is provided.

Kite API tokens may possess broader broker permissions. The read restriction here is enforced by the application's transport allowlist, not by claiming that Kite issued a read-only scope. Someone rewriting code or stealing the token is outside this application guard.

## Data

- Identity: company/security ISIN, with exchange, symbol, token and effective dates on each listing. Kite instrument dumps do not replace the ISIN mapping.
- Evidence: source, original payload/hash, publication time if known, receipt time, availability time, revision and verification state.
- Prospective news availability is max(publication, receipt). An old article downloaded today is not evidence the system possessed yesterday.
- Historical candle exports declare their end-of-bar availability assumption and lack of original-vintage data. Corporate actions, universes, restrictions and historical fees remain unverified until documented.
- Preserve raw observations. Derived features and labels are versioned artifacts. Reject stale, missing, future or contradictory required inputs.
- External-trade imports are observations, not proof of portfolio reconciliation. Multi-broker deduplication, corporate actions and opening balances must precede any allocator using those positions.

## Forecasts and decisions

Return distributions must name the security, as-of time, expiry, horizon, model/calibration identifiers, sample count and evidence IDs. Use separate models and evaluation for intraday, swing and core horizons. Do not compare a one-day expected return to a one-year return without a common decision formulation.

The current sizing function evaluates one new paper entry against caller-supplied existing exposures. It is not a joint portfolio optimizer and does not maintain a portfolio by itself. The coordinator must serialize proposals, update reservations and aggregate both exchanges by ISIN before allowing a second proposal. Missing calibration or validation means abstention.

No pricing model may claim certainty of a maximum/minimum. Source verification confidence and forecast probability are different quantities. Explain decisions from recorded fields/reason codes.

## Money and research fills

Only fully funded, long-only cash-equity research. Intraday cash use is capped at full notional even where a broker might offer more exposure. No overnight short positions or implicit margin.

Broker-reported usable margin is not automatically settled cash. A future coordinator must reconcile and distinguish them. Existing financed or derivative positions in a broker snapshot must be surfaced as unsupported exposure, not silently dropped to make the cash-only portfolio appear safe.

The diagnostic simulator handles one instrument, whole fills, current-fee estimates, adverse slippage and conservative receipt availability. It does not certify historical broker settlement. Unsupported same-day delivery netting is blocked; intraday positions must exit during supplied data or the run fails. No invented final-bar delivery sale.

Before performance certification, replace/extend these assumptions with effective-dated calendars, official security restrictions, corporate-action accounting, matching, rejected/unfilled/partial orders and realistic execution. Netting receivables must never increase spendable cash early.

## Logging and operating limits

Evidence uses append-only SQLite with WAL and a 256 MiB soft quota checked before inserts. Back up using SQLite backup, not by copying a live database alone. The quota is for one database, not a full-disk guarantee; monitor free disk space externally.

Each backtest records a STARTED event, dataset/code hashes and parameters, followed by COMPLETED or FAILED. A crash leaves STARTED for reconciliation. Result files cannot overwrite existing backtest outputs.

Raw broker data and credentials remain private. The dashboard reads only sanitized status/report data and serves on loopback. No API credential entry through the dashboard.

The default collector polls every five minutes on weekdays 08:30–16:15 IST. This is a collection window, not a verified trading-session calendar; holiday and special-weekend collection must be scheduled explicitly. No trade relies on this window.

## Evaluation

Do not use the archive's planned 1,000/1,200 rows as executed evidence. Separate engineering scenarios from statistical trials. Preserve all failures, compare with cash and implementable passive baselines, use chronological untouched tests, account for selection, and report both absolute rupees and returns after recurring costs.

Real-data strategy validation, authentication against the user's account, server deployment and prospective paper observation are NOT performed by this reset.
