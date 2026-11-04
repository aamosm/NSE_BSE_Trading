"""Tick size, price band, market-price protection, SL gap and circuit-breaker tests (hand-computed)."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal as D

import pytest

from marketlab.rules import RuleUnknown
from marketlab.rules.bands import (
    cas_band,
    market_wide_circuit,
    mpp_limits,
    sl_limit_gap_allowed,
    static_band,
)
from marketlab.rules.ticks import tick_size

NOW = date(2026, 11, 4)


@pytest.mark.parametrize("price,tick", [
    ("0.50", "0.01"), ("249.99", "0.01"),
    ("250", "0.05"), ("999.95", "0.05"), ("1000", "0.05"),
    ("1000.05", "0.10"), ("5000", "0.10"),
    ("5000.01", "0.50"), ("10000", "0.50"),
    ("10000.5", "1.00"), ("20000", "1.00"),
    ("20000.01", "5.00"), ("150000", "5.00"),
])
def test_tick_slabs_from_15_apr_2025(price, tick):
    assert tick_size(D(price), NOW) == D(tick)


def test_tick_regime_boundaries():
    assert tick_size(D("1500"), date(2025, 4, 14)) == D("0.05")  # old two-slab regime
    assert tick_size(D("1500"), date(2025, 4, 15)) == D("0.10")  # new six-slab regime
    assert tick_size(D("249"), date(2025, 1, 15)) == D("0.01")
    assert tick_size(D("25000"), date(2025, 1, 15)) == D("0.05")
    with pytest.raises(RuleUnknown):
        tick_size(D("100"), date(2024, 1, 1))


@pytest.mark.parametrize("base,pct,tick,lower,upper", [
    ("100", "5", "0.01", "95.00", "105.00"),
    ("101.37", "2", "0.01", "99.35", "103.39"),    # 99.3426 -> up, 103.3974 -> down
    ("333.33", "20", "0.05", "266.70", "399.95"),  # 266.664 -> up to .05, 399.996 -> down to .05
    ("1500", "10", "0.10", "1350.00", "1650.00"),
])
def test_static_band_is_rounded_inward(base, pct, tick, lower, upper):
    b = static_band(D(base), D(pct), D(tick))
    assert (b.lower, b.upper) == (D(lower), D(upper))


def test_no_upward_movement_caps_at_base():
    b = static_band(D("47.30"), D("5"), D("0.01"), no_upward_movement=True)
    assert (b.lower, b.upper) == (D("44.94"), D("47.30"))  # 47.30 * 0.95 = 44.935 -> 44.94


def test_cas_band_three_percent():
    b = cas_band(D("1234.56"), D("0.10"))
    # 1234.56 * 1.03 = 1271.5968 -> 1271.50 ; 1234.56 * 0.97 = 1197.5232 -> 1197.60
    assert (b.lower, b.upper) == (D("1197.60"), D("1271.50"))


@pytest.mark.parametrize("ltp,lower,upper", [
    ("40", "38.5", "41.5"),     # LTP <= 50: Rs 1.5 absolute
    ("50", "48.5", "51.5"),
    ("200", "194.00", "206.00"),  # LTP > 50: 3%
])
def test_market_price_protection(ltp, lower, upper):
    b = mpp_limits(D(ltp))
    assert (b.lower, b.upper) == (D(lower), D(upper))


@pytest.mark.parametrize("trigger,gap", [("40", "1.5"), ("50", "1.5"), ("100", "3.00"), ("202", "6.06")])
def test_sl_limit_gap(trigger, gap):
    assert sl_limit_gap_allowed(D(trigger)) == D(gap)


@pytest.mark.parametrize("level,at,halt", [
    (10, time(12, 59), 45), (10, time(13, 0), 15), (10, time(14, 29), 15), (10, time(14, 30), 0),
    (15, time(9, 30), 105), (15, time(13, 30), 45), (15, time(14, 0), None),
    (20, time(9, 30), None), (20, time(15, 0), None),
])
def test_market_wide_circuit_breaker(level, at, halt):
    assert market_wide_circuit(level, at).halt_minutes == halt
