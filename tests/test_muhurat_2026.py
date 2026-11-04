"""Muhurat session, Sunday 8 Nov 2026. Expected values transcribed from NSE/CMTR/76941 and NCL/CMPT/77037."""
from datetime import date

import pytest

from conftest import MIS_POLICY, ACCOUNT, NO_POSITION, eq_snapshot, fno_snapshot, ist, order
from marketlab.account import trade_session_date
from marketlab.metrics.performance import trading_sessions_in_year
from marketlab.rules import Exchange, MarketCalendar, Outcome, OrderType, Product, evaluate_order
from marketlab.rules.sessions import SessionKind, session_at

NSE = Exchange.NSE
MUHURAT = date(2026, 11, 8)


@pytest.fixture
def cal():
    return MarketCalendar()


def at(h, m):
    return ist(2026, 11, 8, h, m)


@pytest.mark.parametrize("h, m, cas, kind", [
    (13, 55, False, SessionKind.CLOSED),  # block-deal window only; out of scope
    (14, 5, False, SessionKind.PRE_OPEN_ALL),
    (14, 10, False, SessionKind.PRE_OPEN_LIMIT_ONLY),
    (14, 13, False, SessionKind.PRE_OPEN_RANDOM_CLOSE),
    (14, 16, False, SessionKind.PRE_OPEN_MATCHING),
    (14, 19, False, SessionKind.PRE_OPEN_MATCHING),  # buffer to 14:20
    (14, 20, False, SessionKind.CONTINUOUS),
    (15, 29, False, SessionKind.CONTINUOUS),  # non-CAS stocks trade to 15:30
    (15, 30, False, SessionKind.CLOSED),
    (15, 50, False, SessionKind.POST_CLOSE),
    (16, 0, False, SessionKind.CLOSED),
    (15, 14, True, SessionKind.CONTINUOUS),
    (15, 15, True, SessionKind.CAS_TRANSITION),
    (15, 20, True, SessionKind.CAS_ALL),
    (15, 25, True, SessionKind.CAS_LIMIT_ONLY),
    (15, 28, True, SessionKind.CAS_RANDOM_CLOSE),
    (15, 30, True, SessionKind.CAS_MATCHING),
    (15, 35, True, SessionKind.CLOSED),
    (15, 50, True, SessionKind.POST_CLOSE),
])
def test_muhurat_timetable(cal, h, m, cas, kind):
    assert session_at(at(h, m), NSE, cas, cal) is kind


def test_muhurat_is_a_trading_day_settling_on_monday(cal):
    assert cal.is_trading_day(NSE, MUHURAT) and cal.is_special_session(NSE, MUHURAT)
    assert not cal.is_settlement_day(NSE, MUHURAT)
    assert cal.settlement_date(NSE, MUHURAT) == date(2026, 11, 9)  # M 2026211
    assert cal.settlement_date(NSE, date(2026, 11, 6)) == date(2026, 11, 9)  # M 2026210
    assert cal.settlement_date(NSE, date(2026, 11, 9)) == date(2026, 11, 11)  # 10 Nov holiday; M 2026212
    assert cal.next_trading_day(NSE, date(2026, 11, 6)) == MUHURAT
    assert cal.previous_trading_day(NSE, date(2026, 11, 9)) == MUHURAT
    assert cal.is_first_trading_day_of_week(NSE, date(2026, 11, 9))
    assert cal.session_open(NSE, MUHURAT).isoformat() == "14:05:00"


def test_regular_session_count_excludes_muhurat(cal):
    assert trading_sessions_in_year(cal, NSE, 2026) == 246


def run(o, inst, policy=None):
    return evaluate_order(o, inst, NO_POSITION, ACCOUNT, calendar=MarketCalendar(), policy=policy)


def test_cnc_limit_order_in_muhurat_continuous_session_is_accepted():
    dec = run(order(submitted_at=at(14, 30)), eq_snapshot(as_of=MUHURAT))
    assert dec.accepted, dec.explain()


def test_market_order_in_muhurat_limit_only_preopen_is_blocked():
    dec = run(order(submitted_at=at(14, 11), order_type=OrderType.MARKET, price=None), eq_snapshot(as_of=MUHURAT))
    assert "ORDER_TYPE_NOT_ALLOWED_IN_SESSION" in dec.codes(Outcome.BLOCK)


def test_mis_on_muhurat_is_blocked_until_the_broker_square_off_time_is_loaded():
    dec = run(order(submitted_at=at(14, 30), product=Product.MIS), eq_snapshot(as_of=MUHURAT), policy=MIS_POLICY)
    assert "MIS_CUTOFF_UNKNOWN" in dec.codes(Outcome.BLOCK)


def test_fno_stock_enters_cas_at_1515_on_muhurat():
    dec = run(order(submitted_at=at(15, 16)), fno_snapshot(as_of=MUHURAT))
    assert "SESSION_NOT_ACCEPTING_ORDERS" in dec.codes(Outcome.BLOCK)


def test_trade_book_attribution_uses_the_muhurat_open(cal):
    assert trade_session_date(at(13, 0), cal) is None
    assert trade_session_date(at(14, 30), cal) == MUHURAT
