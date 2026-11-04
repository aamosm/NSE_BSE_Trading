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
    from dataclasses import replace
    from marketlab.rules import MarketCalendar
    assert session_at(ist(2026, 11, 7, 10, 0), NSE, False, cal) is SessionKind.NON_TRADING_DAY  # Saturday
    assert session_at(ist(2026, 11, 10, 10, 0), NSE, False, cal) is SessionKind.NON_TRADING_DAY  # holiday
    # A special session without a loaded timetable still fails closed.
    blocked = MarketCalendar((replace(NSE_2026, special_timetable_opens=(),
                                      special_sessions=frozenset({date(2026, 11, 8)})),))
    with pytest.raises(RuleUnknown):
        session_at(ist(2026, 11, 8, 14, 30), NSE, False, blocked)
    assert not blocked.is_trading_day(NSE, date(2026, 11, 8))


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


# ---- calendar years built from the NSE holiday APIs ---------------------------------------------------------

def _api(dates_with_desc):
    return [{"tradingDate": d, "weekDay": "", "description": desc, "morning_session": None, "evening_session": None}
            for d, desc in dates_with_desc]


def test_year_from_holiday_api_matches_the_circular_year_for_2026():
    from marketlab.rules.calendar import NSE_2026, compare_years, year_from_holiday_api
    trading = _api([(d.strftime("%d-%b-%Y"), "x") for d in sorted(NSE_2026.trading_holidays)]
                   + [("15-Feb-2026", "Mahashivratri"), ("08-Nov-2026", "Diwali Laxmi Pujan*")])
    clearing = _api([(d.strftime("%d-%b-%Y"), "x") for d in sorted(NSE_2026.settlement_holidays)])
    y = year_from_holiday_api(Exchange.NSE, 2026, trading, clearing)
    assert compare_years(NSE_2026, y) == {}
    assert y.special_timetable_opens == ((date(2026, 11, 8), __import__("datetime").time(14, 5)),)
    assert date(2026, 2, 1) in y.weekend_trading_days  # circular-sourced override
    cal = __import__("marketlab.rules", fromlist=["MarketCalendar"]).MarketCalendar((y,))
    assert cal.is_trading_day(Exchange.NSE, date(2026, 11, 8)) and not cal.is_trading_day(Exchange.NSE, date(2026, 11, 10))


def test_special_session_without_a_loaded_timetable_stays_blocked_and_discrepancies_are_reported():
    from marketlab.rules.calendar import NSE_2026, compare_years, year_from_holiday_api
    from marketlab.rules import MarketCalendar
    trading = _api([("26-Jan-2027", "Republic Day"), ("29-Oct-2027", "Diwali*"), ("25-Dec-2027", "Christmas")])
    y = year_from_holiday_api(Exchange.NSE, 2027, trading, _api([("26-Jan-2027", "x")]))
    # a weekday special session without a loaded table closes the regular session AND stays a blocked special session
    assert y.trading_holidays == frozenset({date(2027, 1, 26), date(2027, 10, 29)})
    assert y.special_sessions == frozenset({date(2027, 10, 29)})
    cal = MarketCalendar((y,))
    with pytest.raises(RuleUnknown):
        cal.session_open(Exchange.NSE, date(2027, 10, 29))
    changed = year_from_holiday_api(Exchange.NSE, 2026, _api([("26-Jan-2026", "x")]), _api([]))
    diff = compare_years(NSE_2026, changed)
    assert "2026-03-03" in diff["trading_holidays"]["only_in_first"]


def test_load_calendar_uses_stored_api_vintages_and_falls_back_to_circulars(tmp_path):
    import json
    from marketlab import sources
    from marketlab.rules.calendar import NSE_2026
    cal, rep = sources.load_calendar(tmp_path)
    assert rep["source"] == "CIRCULAR" and cal.is_trading_day(Exchange.NSE, date(2026, 11, 4))
    trading = _api([(d.strftime("%d-%b-%Y"), "x") for d in sorted(NSE_2026.trading_holidays)] + [("08-Nov-2026", "Diwali*")])
    clearing = _api([(d.strftime("%d-%b-%Y"), "x") for d in sorted(NSE_2026.settlement_holidays)])

    def fetch(url):
        return 200, json.dumps({"CM": trading if "trading" in url else clearing}).encode(), None
    sources.collect(tmp_path, date(2026, 11, 4), ["nse_holidays", "nse_clearing_holidays"], fetch=fetch, pause=0)
    cal, rep = sources.load_calendar(tmp_path)
    assert rep["source"] == "NSE_API" and rep["years"] == [2026] and rep["discrepancies"] == {}
    assert cal.settlement_date(Exchange.NSE, date(2026, 11, 8)) == date(2026, 11, 9)
