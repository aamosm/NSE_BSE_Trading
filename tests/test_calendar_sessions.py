"""Calendar and session tests. Expected values are transcribed from the circulars, not from the code."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from conftest import ist
from marketlab.rules import Exchange, RuleUnknown
from marketlab.rules.calendar import NSE_2026
from marketlab.rules.sessions import SessionKind, session_at

NSE = Exchange.NSE

# (date, weekday as printed in NSE/CMTR/73927 section 2.1)
CIRCULAR_TRADING_HOLIDAYS = [
    ("2026-01-26", "Monday"), ("2026-03-03", "Tuesday"), ("2026-03-26", "Thursday"), ("2026-03-31", "Tuesday"),
    ("2026-04-03", "Friday"), ("2026-04-14", "Tuesday"), ("2026-05-01", "Friday"), ("2026-05-28", "Thursday"),
    ("2026-06-26", "Friday"), ("2026-09-14", "Monday"), ("2026-10-02", "Friday"), ("2026-10-20", "Tuesday"),
    ("2026-11-10", "Tuesday"), ("2026-11-24", "Tuesday"), ("2026-12-25", "Friday"),
]


@pytest.mark.parametrize("iso,weekday", CIRCULAR_TRADING_HOLIDAYS)
def test_holiday_transcription_matches_circular_weekday(cal, iso, weekday):
    d = date.fromisoformat(iso)
    assert d.strftime("%A") == weekday
    assert not cal.is_trading_day(NSE, d)


def test_holiday_counts():
    # 15 from the consolidated circular + the ad hoc 15 Jan 2026 closure.
    assert len(NSE_2026.trading_holidays) == 16
    # NCL/CMPT/71904 lists 19 weekday settlement holidays, + 15 Jan ad hoc.
    assert len(NSE_2026.settlement_holidays) == 20


def test_settlement_only_days_are_the_four_from_the_clearing_circular():
    only = NSE_2026.settlement_holidays - NSE_2026.trading_holidays
    assert only == {date(2026, 2, 19), date(2026, 3, 19), date(2026, 4, 1), date(2026, 8, 26)}


@pytest.mark.parametrize("trade,settle", [
    ("2026-11-04", "2026-11-05"),  # Wed -> Thu
    ("2026-11-06", "2026-11-09"),  # Fri -> Mon
    ("2026-11-09", "2026-11-11"),  # Mon -> Wed (10 Nov holiday)
    ("2026-02-18", "2026-02-20"),  # 19 Feb settlement-only holiday
    ("2026-02-19", "2026-02-20"),  # trade on a settlement holiday
    ("2026-03-30", "2026-04-02"),  # 31 Mar trading+settlement holiday, 1 Apr settlement-only holiday
    ("2026-12-24", "2026-12-28"),  # Thu -> Mon (25 Dec holiday)
])
def test_t_plus_1_settlement_dates(cal, trade, settle):
    assert cal.settlement_date(NSE, date.fromisoformat(trade)) == date.fromisoformat(settle)


def test_unloaded_years_fail_closed(cal):
    with pytest.raises(RuleUnknown):
        cal.settlement_date(NSE, date(2026, 12, 31))  # T+1 falls in 2027, not loaded
    with pytest.raises(RuleUnknown):
        cal.is_trading_day(NSE, date(2025, 6, 2))
    with pytest.raises(RuleUnknown):
        cal.is_trading_day(Exchange.BSE, date(2026, 11, 4))  # BSE calendar not yet loaded


@pytest.mark.parametrize("iso,expected", [
    ("2026-01-27", True),   # Tuesday; Monday 26 Jan is a holiday
    ("2026-01-26", False),  # holiday itself
    ("2026-09-15", True),   # Tuesday; Monday 14 Sep is a holiday
    ("2026-11-09", True),   # ordinary Monday
    ("2026-11-11", False),  # Wednesday after the Tuesday holiday
])
def test_first_trading_day_of_week(cal, iso, expected):
    assert cal.is_first_trading_day_of_week(NSE, date.fromisoformat(iso)) is expected


def test_next_trading_day_skips_holiday(cal):
    assert cal.next_trading_day(NSE, date(2026, 11, 9)) == date(2026, 11, 11)


@pytest.mark.parametrize("hh,mm,ss,kind", [
    (8, 59, 59, SessionKind.CLOSED),
    (9, 0, 0, SessionKind.PRE_OPEN_ALL),
    (9, 4, 59, SessionKind.PRE_OPEN_ALL),
    (9, 5, 0, SessionKind.PRE_OPEN_LIMIT_ONLY),
    (9, 7, 59, SessionKind.PRE_OPEN_LIMIT_ONLY),
    (9, 8, 0, SessionKind.PRE_OPEN_RANDOM_CLOSE),
    (9, 10, 0, SessionKind.PRE_OPEN_MATCHING),
    (9, 15, 0, SessionKind.CONTINUOUS),
    (15, 14, 59, SessionKind.CONTINUOUS),
    (15, 15, 0, SessionKind.CAS_TRANSITION),
    (15, 20, 0, SessionKind.CAS_ALL),
    (15, 25, 0, SessionKind.CAS_LIMIT_ONLY),
    (15, 28, 0, SessionKind.CAS_RANDOM_CLOSE),
    (15, 30, 0, SessionKind.CAS_MATCHING),
    (15, 35, 0, SessionKind.CLOSED),
    (15, 50, 0, SessionKind.POST_CLOSE),
    (16, 0, 0, SessionKind.CLOSED),
])
def test_fno_stock_sessions_after_cas_and_new_preopen(cal, hh, mm, ss, kind):
    assert session_at(ist(2026, 11, 4, hh, mm, ss), NSE, True, cal) is kind


@pytest.mark.parametrize("hh,mm,kind", [
    (15, 16, SessionKind.CONTINUOUS),
    (15, 29, SessionKind.CONTINUOUS),
    (15, 30, SessionKind.CLOSED),
    (15, 45, SessionKind.CLOSED),
    (15, 50, SessionKind.POST_CLOSE),
])
def test_non_fno_stock_has_no_cas(cal, hh, mm, kind):
    assert session_at(ist(2026, 11, 4, hh, mm), NSE, False, cal) is kind


def test_regimes_before_cas_and_before_new_preopen(cal):
    # 15 Jul 2026: old pre-open (random close in the 8th minute), no CAS, post-close 15:40.
    assert session_at(ist(2026, 7, 15, 9, 6), NSE, True, cal) is SessionKind.PRE_OPEN_ALL
    assert session_at(ist(2026, 7, 15, 9, 7), NSE, True, cal) is SessionKind.PRE_OPEN_RANDOM_CLOSE
    assert session_at(ist(2026, 7, 15, 15, 20), NSE, True, cal) is SessionKind.CONTINUOUS
    assert session_at(ist(2026, 7, 15, 15, 40), NSE, True, cal) is SessionKind.POST_CLOSE
    # 20 Aug 2026: CAS live, old pre-open still in force.
    assert session_at(ist(2026, 8, 20, 9, 6), NSE, True, cal) is SessionKind.PRE_OPEN_ALL
    assert session_at(ist(2026, 8, 20, 15, 16), NSE, True, cal) is SessionKind.CAS_TRANSITION


def test_non_trading_days_and_special_sessions(cal):
    assert session_at(ist(2026, 11, 7, 10, 0), NSE, False, cal) is SessionKind.NON_TRADING_DAY  # Saturday
    assert session_at(ist(2026, 11, 10, 10, 0), NSE, False, cal) is SessionKind.NON_TRADING_DAY  # holiday
    with pytest.raises(RuleUnknown):
        session_at(ist(2026, 11, 8, 18, 0), NSE, False, cal)  # Muhurat: timetable not loaded


def test_session_requires_known_fno_status_after_cas(cal):
    with pytest.raises(RuleUnknown):
        session_at(ist(2026, 11, 4, 10, 0), NSE, None, cal)


def test_timezone_handling(cal):
    with pytest.raises(ValueError):
        session_at(datetime(2026, 11, 4, 10, 0), NSE, False, cal)
    # 04:00 UTC == 09:30 IST
    assert session_at(datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc), NSE, False, cal) is SessionKind.CONTINUOUS


# ---- review finding R10: Budget Sunday 1 Feb 2026 was a full trading session -------------------

def test_r10_budget_sunday_is_a_trading_day_with_t_plus_1_settlement(cal):
    sunday = date(2026, 2, 1)
    assert cal.is_trading_day(Exchange.NSE, sunday) and not cal.is_special_session(Exchange.NSE, sunday)
    assert not cal.is_settlement_day(Exchange.NSE, sunday)  # no T0 session: settlement holiday
    assert cal.settlement_date(Exchange.NSE, sunday) == date(2026, 2, 2)  # NCL/CMPT/72384
    assert cal.settlement_date(Exchange.NSE, date(2026, 1, 30)) == date(2026, 2, 2)  # Friday's trades too
    assert cal.next_trading_day(Exchange.NSE, date(2026, 1, 30)) == sunday
    assert cal.previous_trading_day(Exchange.NSE, date(2026, 2, 2)) == sunday


def test_r10_budget_sunday_uses_the_standard_pre_cas_timetable(cal):
    from marketlab.rules.sessions import SessionKind, session_at
    at = lambda h, m: ist(2026, 2, 1, h, m)  # noqa: E731
    assert session_at(at(9, 4), Exchange.NSE, False, cal) is SessionKind.PRE_OPEN_ALL
    assert session_at(at(10, 0), Exchange.NSE, False, cal) is SessionKind.CONTINUOUS
    assert session_at(at(15, 29), Exchange.NSE, True, cal) is SessionKind.CONTINUOUS  # CAS starts 3 Aug 2026


def test_weekend_trading_days_are_validated():
    from marketlab.rules.calendar import NSE_2026, CalendarYear, MarketCalendar
    from dataclasses import replace
    bad = replace(NSE_2026, weekend_trading_days=frozenset({date(2026, 2, 2)}))  # a Monday
    with pytest.raises(ValueError):
        MarketCalendar((bad,))
