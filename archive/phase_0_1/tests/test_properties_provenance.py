"""Property-based invariants and provenance integrity checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from marketlab.rules import Exchange, Side, bands, calendar, charges, instruments, sessions, ticks
from marketlab.rules import broker as broker_rules
from marketlab.rules import mtf as mtf_rules
from marketlab.ledger import book as ledger_book
from marketlab.rules.provenance import SOURCES, Cite, SourceKind, Status

NOW = date(2026, 11, 4)
TICKS = [D("0.01"), D("0.05"), D("0.10"), D("0.50"), D("1.00"), D("5.00")]
prices = st.decimals(min_value=D("0.01"), max_value=D("100000"), places=2, allow_nan=False, allow_infinity=False)


@given(prices, st.sampled_from(TICKS))
def test_tick_rounding_brackets_price(p, t):
    lo, hi = ticks.floor_to_tick(p, t), ticks.ceil_to_tick(p, t)
    assert ticks.is_on_tick(lo, t) and ticks.is_on_tick(hi, t)
    assert lo <= p <= hi and hi - lo in (D("0"), t)


@given(prices, prices)
def test_tick_size_is_monotone_in_price(a, b):
    lo, hi = sorted((a, b))
    assert ticks.tick_size(lo, NOW) <= ticks.tick_size(hi, NOW)


@given(prices, st.sampled_from([D("2"), D("5"), D("10"), D("20")]))
def test_band_contains_on_tick_base_and_stays_inside_percentage(p, pct):
    t = ticks.tick_size(p, NOW)
    base = ticks.floor_to_tick(p, t)
    if base <= 0:
        return
    b = bands.static_band(base, pct, t)
    assert ticks.is_on_tick(b.lower, t) and ticks.is_on_tick(b.upper, t)
    assert b.lower <= base <= b.upper
    assert b.upper <= base * (1 + pct / 100) and b.lower >= base * (1 - pct / 100)


@settings(max_examples=300)
@given(prices, st.integers(min_value=1, max_value=100000), st.sampled_from(list(charges.TradeKind)),
       st.sampled_from(list(Side)))
def test_charges_are_non_negative_and_brokerage_capped(p, q, kind, side):
    c = charges.order_charges(charges.ZERODHA_2026_11_04, exchange=Exchange.NSE, kind=kind, side=side, price=p,
                              quantity=q, trade_date=NOW)
    parts = (c.brokerage, c.stt, c.exchange_txn, c.sebi, c.ipft, c.stamp, c.gst)
    assert all(x >= 0 for x in parts)
    assert c.brokerage <= D("20.00")
    if side is Side.SELL:
        assert c.stamp == 0


def _all_cites() -> list[Cite]:
    found: list[Cite] = []
    for mod in (bands, broker_rules, calendar, charges, instruments, mtf_rules, sessions, ticks):
        for v in vars(mod).values():
            if isinstance(v, Cite):
                found.append(v)
            elif isinstance(v, dict):
                found += [x for x in v.values() if isinstance(x, Cite)]
    found += [c for y in calendar.DEFAULT_YEARS for c in y.cites]
    found += [r.cite for r in ticks.TICK_REGIMES]
    found += list(charges.ZERODHA_2026_11_04.cites)
    found += [r_.cite for r_ in instruments.SERIES_RULES.values()]
    found += [c for r in instruments.STAGE_RULES for c in r.r.cites]
    found += list(ledger_book.LEDGER_CITES)
    return found


def test_every_rule_cites_a_registered_source():
    cites = _all_cites()
    assert len(cites) > 40
    for c in cites:
        assert all(s in SOURCES for s in c.sources)
        if c.status is not Status.UNKNOWN:
            assert c.sources


def test_primary_status_requires_an_official_exchange_or_regulator_source():
    official = {SourceKind.EXCHANGE, SourceKind.REGULATOR, SourceKind.CLEARING}
    for c in _all_cites():
        if c.status is Status.PRIMARY:
            assert any(SOURCES[s].kind in official for s in c.sources), c


def test_sources_have_locations_and_check_dates():
    for s in SOURCES.values():
        assert s.url and s.checked_on == date(2026, 11, 4)
