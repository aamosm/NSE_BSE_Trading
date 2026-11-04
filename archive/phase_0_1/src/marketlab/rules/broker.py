"""Zerodha / Kite Connect rules relevant to order validation (observed 2026-11-04)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .provenance import Cite, Status
from .sessions import CAS_FROM
from .types import IST, RuleUnknown

# ---- MIS (intraday) auto square-off ----------------------------------------------------------

MIS_CUTOFF_CITE = Cite(("ZERODHA/CAS",), Status.BROKER_OFFICIAL,
                       "From 3 Aug 2026: MIS auto square-off 15:12 for F&O (CAS) stocks, 15:25 for other stocks. "
                       "New MIS orders are rejected after the cut-off.")


def mis_cutoff(on: date, has_derivatives: bool | None) -> time:
    if on < CAS_FROM:
        raise RuleUnknown("MIS cut-off before 3 Aug 2026 is not verified (sources show both 15:20 and 15:25)")
    if has_derivatives is None:
        raise RuleUnknown("F&O status unknown, so the MIS cut-off is unknown")
    return time(15, 12) if has_derivatives else time(15, 25)


# ---- Kite Connect order API -----------------------------------------------------------------

MARKET_PROTECTION_CITE = Cite(("ZERODHA/KITE-API-FAQ", "KITE/ORDERS", "NSE/CMTR/68802"), Status.BROKER_OFFICIAL,
                              "API MARKET and SL-M orders must carry market_protection (-1 auto or >0..100 %); 0 is "
                              "rejected. Kite converts them to protected limit orders; NSE pre-emptively rejects "
                              "true algo market orders in the normal market from 7 Jul 2025.")
RATE_LIMIT_CITE = Cite(("KITE/LIMITS", "ZERODHA/KITE-API-FAQ"), Status.BROKER_OFFICIAL,
                       "10 orders/second per client account (HTTP 429 beyond; invalid requests count), 400/minute, "
                       "5,000/day per user or API key, 25 modifications per order.")
STATIC_IP_CITE = Cite(("ZERODHA/STATIC-IP", "ZERODHA/KITE-API-FAQ"), Status.CONFLICTING,
                      "Static IP required for API order placement. The static-IP article says from 1 Apr 2026; the "
                      "API FAQ says 1 Apr 2025. Either way it is in force now. Max 2 IPs, 1 change per week.")
TAG_MAX_LEN = 20
ORDERS_PER_SECOND = 10
ORDERS_PER_MINUTE = 400
ORDERS_PER_DAY = 5000
MODIFICATIONS_PER_ORDER = 25


def market_protection_valid(pct: Decimal | None) -> bool:
    if pct is None:
        return False
    return pct == Decimal("-1") or Decimal("0") < pct <= Decimal("100")


def tag_valid(tag: str | None) -> bool:
    return tag is None or (0 < len(tag) <= TAG_MAX_LEN and tag.isascii() and tag.isalnum())


@dataclass
class OrderRateLimiter:
    """Deterministic limiter for simulated order submission (no wall clock).

    Callers must pass *every* request that reaches the broker, including ones our own validation
    would reject, because Kite counts blocked invalid requests too. Requests refused here (the
    simulated HTTP 429) are not counted: ASSUMPTION, not stated by Kite.
    The daily window is the IST date of the timestamp.
    """

    _second: deque[datetime] = field(default_factory=deque)
    _minute: deque[datetime] = field(default_factory=deque)
    _day: date | None = None
    _day_count: int = 0

    def try_acquire(self, ts: datetime) -> bool:
        if ts.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware")
        for q, width in ((self._second, timedelta(seconds=1)), (self._minute, timedelta(minutes=1))):
            while q and ts - q[0] >= width:
                q.popleft()
        d = ts.astimezone(IST).date()
        if d != self._day:
            self._day, self._day_count = d, 0
        allowed = (len(self._second) < ORDERS_PER_SECOND and len(self._minute) < ORDERS_PER_MINUTE
                   and self._day_count < ORDERS_PER_DAY)
        if allowed:
            self._second.append(ts)
            self._minute.append(ts)
            self._day_count += 1
        return allowed
