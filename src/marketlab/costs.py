"""2026-11-04 resident cash-equity estimates; reconcile account class and contract-note rounding."""
from __future__ import annotations
from datetime import date
from decimal import Decimal as D
from .common import money

OBSERVED_ON = date(2026, 11, 4)
DP = D("15.34")


def charges(value, *, side, style, exchange="NSE", bse_group=None, dp=False):
    value = money(value)
    if value <= 0 or side not in {"BUY", "SELL"} or style not in {"delivery", "intraday"}:
        raise ValueError("Positive turnover, side and cash trade style required")
    if exchange not in {"NSE", "BSE"}:
        raise ValueError("Only NSE/BSE cash equities")
    if exchange == "BSE" and bse_group not in {"A", "B", "T", "X", "XT", "Z", "ZP", "SS", "ST", "M", "MT", "TS", "MS"}:
        raise ValueError("A verified supported BSE group is required")
    txn = D(".0000307") if exchange == "NSE" else {
        "X": D(".001"), "XT": D(".001"), "Z": D(".001"), "ZP": D(".001"),
        "SS": D(".01"), "ST": D(".01"), "M": D(".0000275"),
        "MT": D(".0000275"), "TS": D(".0000275"), "MS": D(".0000275"),
    }.get(bse_group, D(".0000375"))
    brokerage = min(D("20"), value * D(".0003")) if style == "intraday" else D("0")
    stt = value * (D(".001") if style == "delivery" else D(".00025") if side == "SELL" else D("0"))
    stamp = value * (D(".00015") if style == "delivery" else D(".00003")) if side == "BUY" else D("0")
    exchange_fee, sebi = value * txn, value * D(".000001")
    ipft = value * D(".000000001") if exchange == "NSE" else D("0")
    gst = (brokerage + exchange_fee + sebi + ipft) * D(".18")
    parts = dict(brokerage=brokerage, stt=stt, stamp=stamp, exchange=exchange_fee, sebi=sebi, ipft=ipft, gst=gst)
    result = {k: money(v) for k, v in parts.items()}
    result["dp"] = DP if dp and style == "delivery" and side == "SELL" else D("0")
    return result


def total_charges(value, **kw):
    return sum(charges(value, **kw).values(), D("0"))
