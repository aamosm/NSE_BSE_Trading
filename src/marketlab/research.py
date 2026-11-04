"""Forecast contract and conservative paper proposal sizing, not a trained model."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal as D
import math
import re

from .common import timestamp
from .costs import total_charges
from .rules import (
    AccountState, Exchange, InstrumentSnapshot, MarketCalendar, OrderRequest, OrderType, PositionState, Product,
    Side, evaluate_order,
)
from .rules import Policy as RulesPolicy
from .rules.types import Decision


@dataclass(frozen=True)
class Forecast:
    isin: str
    exchange: str
    sector: str
    sleeve: str
    as_of: datetime
    expires_at: datetime
    horizon_sessions: int
    mean_return: float
    q10: float
    q50: float
    q90: float
    mean_standard_error: float
    probability_positive: float
    samples: int
    model_id: str
    calibration_id: str
    evidence_ids: tuple[str, ...]
    validated_for_paper: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"INE[A-Z0-9]{9}", self.isin) or not self.sector.strip():
            raise ValueError("Verified security identity and sector are required")
        values = (self.mean_return, self.q10, self.q50, self.q90,
                  self.mean_standard_error, self.probability_positive)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Forecast numbers must be finite")
        if not self.q10 <= self.q50 <= self.q90 or self.q10 < -1:
            raise ValueError("Return quantiles are invalid")
        if not 0 <= self.probability_positive <= 1 or self.mean_standard_error < 0:
            raise ValueError("Probability or uncertainty is invalid")
        if type(self.horizon_sessions) is not int or type(self.samples) is not int or self.horizon_sessions <= 0 or self.samples < 0:
            raise ValueError("Horizon and sample count are invalid")
        if timestamp(self.expires_at) <= timestamp(self.as_of):
            raise ValueError("Forecast expiry must follow its observation time")


@dataclass(frozen=True)
class Policy:
    cash_reserve: float = .20
    stock_cap: float = .20
    sector_cap: float = .40
    risk_per_entry: float = .005
    minimum_samples: int = 100
    max_spread_bps: float = 15
    max_participation: float = .001
    # Caps are illustrative research constraints, not recommended allocations.
    sleeve_caps: dict = field(default_factory=lambda: {"core": .50, "swing": .20, "intraday": .10})

    def __post_init__(self):
        rates = [self.cash_reserve, self.stock_cap, self.sector_cap, self.risk_per_entry,
                 self.max_participation, *self.sleeve_caps.values()]
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in rates):
            raise ValueError("Invalid policy fractions")
        if self.minimum_samples <= 0 or not 0 <= self.max_spread_bps < 10000:
            raise ValueError("Invalid policy limits")


def exchange_rules_decision(forecast: Forecast, snapshot: InstrumentSnapshot, *, quantity: int, price,
                            submit_at, calendar: MarketCalendar | None = None) -> Decision:
    """Run the proposed paper entry through the exchange/broker rules engine as a LIMIT buy.

    Core and swing sleeves are delivery (CNC); the intraday sleeve is MIS, always fully funded here.
    The snapshot must describe this security on the submission date; the engine rejects stale, unknown
    or restricted inputs (T2T, surveillance, bands, ticks, sessions, suspension, call auctions).
    """
    product = Product.MIS if forecast.sleeve == "intraday" else Product.CNC
    order = OrderRequest(submitted_at=timestamp(submit_at), exchange=Exchange(forecast.exchange), side=Side.BUY,
                         product=product, order_type=OrderType.LIMIT, quantity=quantity, price=D(str(price)))
    return evaluate_order(order, snapshot, PositionState(), AccountState(), calendar=calendar or MarketCalendar(),
                          policy=RulesPolicy(allowed_products=frozenset({Product.CNC, Product.MIS})))


def paper_proposal(forecast: Forecast, *, at, price, equity, available_cash,
                   known_status: bool, restricted: bool, spread_bps: float,
                   median_daily_volume: int, existing_stock=0, existing_sector=0,
                   existing_sleeve=0, bse_group=None, status_as_of=None, quote_as_of=None, policy=Policy(),
                   snapshot: InstrumentSnapshot | None = None, calendar: MarketCalendar | None = None,
                   submit_at=None):
    reasons = []
    f, t = forecast, timestamp(at)
    if snapshot is None:
        reasons.append("EXCHANGE_RULES_NOT_CHECKED")
    elif snapshot.isin != f.isin or str(snapshot.exchange) != f.exchange:
        reasons.append("SNAPSHOT_IDENTITY_MISMATCH")
    if f.validated_for_paper is not True or not f.model_id or not f.calibration_id:
        reasons.append("MODEL_NOT_VALIDATED")
    if not timestamp(f.as_of) <= t < timestamp(f.expires_at):
        reasons.append("STALE_OR_FUTURE_FORECAST")
    if f.samples < policy.minimum_samples:
        reasons.append("INSUFFICIENT_SAMPLES")
    if not f.evidence_ids:
        reasons.append("MISSING_EVIDENCE")
    if known_status is not True or restricted is not False:
        reasons.append("UNKNOWN_OR_RESTRICTED_SECURITY")
    if status_as_of is None or quote_as_of is None:
        reasons.append("STALE_OR_MISSING_MARKET_INPUT")
    elif (timestamp(status_as_of).date() != t.date() or timestamp(status_as_of) > t
          or not timedelta(0) <= t-timestamp(quote_as_of) <= timedelta(minutes=5)):
        reasons.append("STALE_OR_MISSING_MARKET_INPUT")
    if f.exchange not in {"NSE", "BSE"} or f.sleeve not in policy.sleeve_caps:
        reasons.append("UNSUPPORTED_MARKET_OR_SLEEVE")
    if not math.isfinite(spread_bps) or spread_bps < 0 or spread_bps > policy.max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE_OR_UNKNOWN")
    if median_daily_volume <= 0:
        reasons.append("UNKNOWN_LIQUIDITY")
    p, e, cash = D(str(price)), D(str(equity)), D(str(available_cash))
    amounts = [p, e, cash, D(str(existing_stock)), D(str(existing_sector)), D(str(existing_sleeve))]
    if not all(x.is_finite() for x in amounts) or p <= 0 or e <= 0 or min(amounts[2:]) < 0:
        raise ValueError("Invalid portfolio amounts")
    if reasons:
        return {"action": "ABSTAIN", "quantity": 0, "reasons": reasons, "live_orders": False}
    style = "intraday" if f.sleeve == "intraday" else "delivery"
    budget = max(D("0"), min(
        cash - e * D(str(policy.cash_reserve)),
        e * D(str(policy.stock_cap)) - D(str(existing_stock)),
        e * D(str(policy.sector_cap)) - D(str(existing_sector)),
        e * D(str(policy.sleeve_caps[f.sleeve])) - D(str(existing_sleeve))))
    downside = max(.02, -f.q10)  # Risk estimate, never a guaranteed maximum loss.
    qty = max(0, min(int(budget / p),
        int(e * D(str(policy.risk_per_entry)) / (p * D(str(downside)))),
        int(median_daily_volume * policy.max_participation)))
    while qty:
        buy = total_charges(p * qty, side="BUY", style=style, exchange=f.exchange, bse_group=bse_group)
        if p * qty + buy <= budget:
            break
        qty -= 1
    if not qty:
        return {"action": "ABSTAIN", "quantity": 0, "reasons": ["CASH_RISK_OR_INTEGER_SHARE_LIMIT"], "live_orders": False}
    rules = exchange_rules_decision(f, snapshot, quantity=qty, price=p, submit_at=submit_at or t, calendar=calendar)
    if not rules.accepted:
        return {"action": "ABSTAIN", "quantity": 0, "reasons": ["EXCHANGE_RULE_BLOCK"],
                "rule_codes": sorted(c.code for c in rules.blocks), "live_orders": False}
    exit_cost = total_charges(p * qty, side="SELL", style=style, exchange=f.exchange,
                              bse_group=bse_group, dp=True)
    cost_fraction = float((buy + exit_cost) / (p * qty)) + spread_bps / 10000
    # An uncertainty penalty, not a confidence interval without calibration.
    net_score = f.mean_return - 2 * f.mean_standard_error - cost_fraction
    if net_score <= 0:
        return {"action": "ABSTAIN", "quantity": 0, "reasons": ["EDGE_NOT_ABOVE_COST_AND_UNCERTAINTY"],
                "net_score": net_score, "live_orders": False}
    return {"action": "PAPER_BUY_PROPOSAL", "quantity": qty, "isin": f.isin,
            "sleeve": f.sleeve, "net_score": net_score, "round_trip_cost_estimate": str(buy + exit_cost),
            "reasons": ["COST_AND_RISK_GATES_PASSED"], "evidence_ids": f.evidence_ids,
            "rule_warnings": sorted(c.code for c in rules.warnings), "snapshot_id": snapshot.snapshot_id,
            "model_id": f.model_id, "live_orders": False}


def explain(proposal):
    meanings = {
        "MODEL_NOT_VALIDATED": "The forecasting model has not passed paper-trading validation.",
        "STALE_OR_FUTURE_FORECAST": "The forecast is expired or was not available at this decision time.",
        "INSUFFICIENT_SAMPLES": "There are too few evaluated examples.",
        "MISSING_EVIDENCE": "The forecast has no linked evidence.",
        "UNKNOWN_OR_RESTRICTED_SECURITY": "Required security status is unknown or trading is restricted.",
        "STALE_OR_MISSING_MARKET_INPUT": "Security status or the price observation is missing, stale or from the future.",
        "UNSUPPORTED_MARKET_OR_SLEEVE": "The market or portfolio category is unsupported.",
        "SPREAD_TOO_WIDE_OR_UNKNOWN": "The bid-ask spread is unknown or exceeds the limit.",
        "UNKNOWN_LIQUIDITY": "Trading-volume evidence is missing.",
        "CASH_RISK_OR_INTEGER_SHARE_LIMIT": "Cash, risk or whole-share limits leave no affordable quantity.",
        "EDGE_NOT_ABOVE_COST_AND_UNCERTAINTY": "Estimated upside does not cover costs and the uncertainty penalty.",
        "COST_AND_RISK_GATES_PASSED": "A paper proposal passed the configured cash, cost and risk checks.",
        "EXCHANGE_RULES_NOT_CHECKED": "No dated security snapshot was supplied, so exchange and broker rules "
                                      "could not be checked.",
        "SNAPSHOT_IDENTITY_MISMATCH": "The security snapshot does not match the forecast's ISIN or exchange.",
        "EXCHANGE_RULE_BLOCK": "Exchange or broker rules would reject this order; see rule_codes.",
    }
    return " ".join(meanings.get(x, "Unknown reason: " + x) for x in proposal["reasons"])
