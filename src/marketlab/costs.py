"""Cash-equity cost estimates: a thin wrapper over the cited, effective-dated rules.charges schedule.

There is one fee implementation (marketlab.rules.charges). This module keeps the string-based API used
by the diagnostic backtest and paper sizing, and estimates ONE order as if it were the only fill of its
security, kind and side that day: STT is then rounded to the rupee as the day-level bill would round it
(``rules.charges.day_charges``). Several orders in one security and day must use ``day_charges``.
Stamp-duty allocation stays an explicit unresolved assumption; DP is reconciled from the funds statement.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal as D
from .common import money
from .rules.charges import ZERODHA_2026_11_04 as SCHEDULE, TradeKind, order_charges, round_rupee
from .rules.types import Exchange, Side

OBSERVED_ON = SCHEDULE.observed_on
DP = SCHEDULE.dp_charge_per_scrip_incl_gst
BSE_GROUPS = frozenset({"A", "B", "T", "X", "XT", "Z", "ZP", "SS", "ST", "M", "MT", "TS", "MS"})
ASSUMPTIONS = ("STT_AGGREGATION_UNRECONCILED", "STAMP_ALLOCATION_UNRESOLVED", "DP_FROM_FUNDS_STATEMENT")


def charges(value, *, side, style, exchange="NSE", bse_group=None, dp=False, trade_date: date = OBSERVED_ON):
    """Charges of one order. ``bse_group`` must come from trusted listing data (a dated security snapshot)."""
    value = money(value)
    if value <= 0 or side not in {"BUY", "SELL"} or style not in {"delivery", "intraday"}:
        raise ValueError("Positive turnover, side and cash trade style required")
    if exchange not in {"NSE", "BSE"}:
        raise ValueError("Only NSE/BSE cash equities")
    if exchange == "BSE" and bse_group not in BSE_GROUPS:
        raise ValueError("A verified supported BSE group from listing data is required")
    kind = TradeKind.DELIVERY if style == "delivery" else TradeKind.INTRADAY
    c = order_charges(SCHEDULE, exchange=Exchange(exchange), kind=kind, side=Side(side), price=value, quantity=1,
                      trade_date=trade_date, bse_group=bse_group if exchange == "BSE" else None)
    stt = round_rupee(value * SCHEDULE.stt_pct[(kind, Side(side))] / 100)
    result = dict(brokerage=c.brokerage, stt=stt, stamp=c.stamp, exchange=c.exchange_txn, sebi=c.sebi,
                  ipft=c.ipft, gst=c.gst)
    result["dp"] = DP if dp and style == "delivery" and side == "SELL" else D("0")
    return result


def total_charges(value, **kw):
    return sum(charges(value, **kw).values(), D("0"))
