"""Market and broker rules for NSE/BSE cash equities (Zerodha as the execution broker).

Every encoded rule cites a source in ``provenance.SOURCES`` with a verification ``Status``.
See docs/RULES_REGISTER.md for the human-readable register.
"""

from .calendar import MarketCalendar
from .engine import evaluate_order
from .types import (
    IST,
    AccountState,
    Decision,
    Exchange,
    Framework,
    InstrumentSnapshot,
    OrderRequest,
    OrderType,
    Outcome,
    Policy,
    PositionState,
    Product,
    RuleUnknown,
    Side,
    SurveillanceFlag,
    Validity,
)

__all__ = [
    "IST", "AccountState", "Decision", "Exchange", "Framework", "InstrumentSnapshot", "MarketCalendar",
    "OrderRequest", "OrderType", "Outcome", "Policy", "PositionState", "Product", "RuleUnknown", "Side",
    "SurveillanceFlag", "Validity", "evaluate_order",
]
