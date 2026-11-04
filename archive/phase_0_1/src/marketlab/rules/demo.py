"""Print rule decisions for a handful of synthetic orders: ``python -m marketlab.rules.demo``.

All instruments are synthetic. No broker is contacted.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal as D

from . import (
    IST,
    AccountState,
    Exchange,
    Framework,
    InstrumentSnapshot,
    MarketCalendar,
    OrderRequest,
    OrderType,
    PositionState,
    Product,
    Side,
    SurveillanceFlag,
    evaluate_order,
)
from .charges import ZERODHA_2026_11_04, TradeKind, order_charges


def main() -> None:
    cal = MarketCalendar()
    day = date(2026, 11, 4)
    eq = InstrumentSnapshot(
        as_of=day, exchange=Exchange.NSE, symbol="DEMOEQ", isin="INE000D00010", series="EQ", has_derivatives=False,
        base_price=D("200.00"), price_band_pct=D("20"), tick_reference_price=D("198.40"), ltp=D("201.00"),
        mis_eligible=True, mtf_eligible=True, var_pct=D("12.5"), elm_pct=D("3.5"), in_nifty500=True,
    )
    be = replace(eq, symbol="DEMOBE", series="BE", base_price=D("12.00"), price_band_pct=D("5"),
                 tick_reference_price=D("12.00"), ltp=D("12.10"))
    gsm3 = replace(be, symbol="DEMOGSM", surveillance=frozenset({SurveillanceFlag(Framework.GSM, 3)}))
    acct = AccountState(ddpi_enabled=True, resident_individual=True)
    at = lambda h, m: datetime(2026, 11, 4, h, m, tzinfo=IST)  # noqa: E731
    base = OrderRequest(submitted_at=at(10, 0), exchange=Exchange.NSE, side=Side.BUY, product=Product.CNC,
                        order_type=OrderType.LIMIT, quantity=10, price=D("201.00"))
    cases = [
        ("Delivery buy, normal stock", base, eq, PositionState()),
        ("Intraday (MIS) buy of a trade-for-trade stock", replace(base, product=Product.MIS, price=D("12.10")), be,
         PositionState()),
        ("Sell T2T shares bought this morning", replace(base, side=Side.SELL, price=D("12.10")), be,
         PositionState(bought_today_qty=10)),
        ("Buy a GSM stage III stock on a Wednesday", replace(base, price=D("12.10")), gsm3, PositionState()),
        ("BTST: sell yesterday's purchase", replace(base, side=Side.SELL), eq, PositionState(t1_qty=10)),
        ("API market order without market protection", replace(base, order_type=OrderType.MARKET, price=None), eq,
         PositionState()),
        ("API market order with 2% protection", replace(base, order_type=OrderType.MARKET, price=None,
                                                       market_protection_pct=D("2")), eq, PositionState()),
        ("MTF buy", replace(base, product=Product.MTF), eq, PositionState()),
    ]
    for title, o, inst, pos in cases:
        dec = evaluate_order(o, inst, pos, acct, calendar=cal)
        print(f"\n== {title}\n{dec.explain()}")
    c = order_charges(ZERODHA_2026_11_04, exchange=Exchange.NSE, kind=TradeKind.DELIVERY, side=Side.BUY,
                      price=D("201.00"), quantity=10, trade_date=day)
    print(f"\n== Charges for the delivery buy (turnover Rs {c.turnover}): STT {c.stt}, exchange {c.exchange_txn}, "
          f"SEBI {c.sebi}, stamp {c.stamp}, GST {c.gst} -> total Rs {c.total}")


if __name__ == "__main__":
    main()
