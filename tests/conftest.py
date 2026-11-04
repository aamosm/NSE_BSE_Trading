from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from marketlab.rules import (
    IST,
    AccountState,
    Exchange,
    InstrumentSnapshot,
    MarketCalendar,
    OrderRequest,
    OrderType,
    Policy,
    PositionState,
    Product,
    Side,
)

TODAY = date(2026, 11, 4)  # Wednesday, a regular NSE trading day


def ist(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


@pytest.fixture(scope="session")
def cal() -> MarketCalendar:
    return MarketCalendar()


def eq_snapshot(**kw) -> InstrumentSnapshot:
    """Non-F&O NSE EQ stock, previous close 200.00, 20% band (160.00-240.00), tick 0.01."""
    base = InstrumentSnapshot(
        as_of=TODAY, exchange=Exchange.NSE, symbol="TESTEQ", isin="INE000T00011", series="EQ",
        has_derivatives=False, base_price=D("200.00"), price_band_pct=D("20"),
        tick_reference_price=D("198.40"), ltp=D("201.00"), surveillance=frozenset(),
        in_periodic_call_auction=False, suspended=False, special_preopen_today=False,
        mis_eligible=True, mtf_eligible=True, var_pct=D("12.5"), elm_pct=D("3.5"), in_nifty500=True,
        snapshot_id="SNAP-EQ",
    )
    return replace(base, **kw)


def fno_snapshot(**kw) -> InstrumentSnapshot:
    """F&O stock, previous close 1500.00, tick 0.10 (reference close 1490), no static band."""
    return eq_snapshot(symbol="TESTFNO", isin="INE000T00029", has_derivatives=True, base_price=D("1500.00"),
                       price_band_pct=None, tick_reference_price=D("1490.00"), ltp=D("1502.00"),
                       snapshot_id="SNAP-FNO", **kw)


def order(**kw) -> OrderRequest:
    base = OrderRequest(submitted_at=ist(2026, 11, 4, 10, 0), exchange=Exchange.NSE, side=Side.BUY,
                        product=Product.CNC, order_type=OrderType.LIMIT, quantity=10, price=D("201.00"))
    return replace(base, **kw)


NO_POSITION = PositionState()
MTF_ACCOUNT = AccountState(ddpi_enabled=True, resident_individual=True)
MIS_POLICY = Policy(allowed_products=frozenset({Product.CNC, Product.MTF, Product.MIS}))
