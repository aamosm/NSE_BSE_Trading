"""Trading and settlement calendars.

Only years whose holiday lists were read from an official source are loaded. Any date
outside a loaded year raises ``RuleUnknown`` so that replay over unloaded history fails
loudly instead of silently treating every weekday as a trading day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta

from .provenance import Cite, Status
from .types import Exchange, RuleUnknown

REGULAR_OPEN = time(9, 0)  # pre-open order entry on a regular trading day (NSE/CMTR/73927)

T_PLUS_1_FROM = date(2023, 1, 27)
T_PLUS_1_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                     "All securities moved to T+1 rolling settlement effective 27 Jan 2023 (section 1.5).")


@dataclass(frozen=True, slots=True)
class CalendarYear:
    exchange: Exchange
    year: int
    trading_holidays: frozenset[date]  # weekday closures
    settlement_holidays: frozenset[date]  # weekday settlement closures (superset of most trading holidays)
    special_sessions: frozenset[date] = frozenset()  # special sessions whose timetable is NOT loaded: blocked
    weekend_trading_days: frozenset[date] = frozenset()  # full weekend sessions at standard timings
    # Special sessions with a loaded timetable (rules.sessions.SPECIAL_TIMETABLES): date -> pre-open start.
    # They are trading days with settlement obligations; ordinary weekday hours never apply to them.
    special_timetable_opens: tuple[tuple[date, time], ...] = ()
    cites: tuple[Cite, ...] = field(default=())


def _d(s: str) -> date:
    return date.fromisoformat(s)


NSE_2026 = CalendarYear(
    exchange=Exchange.NSE,
    year=2026,
    trading_holidays=frozenset(map(_d, [
        "2026-01-15",  # Maharashtra municipal elections (ad hoc; announced Jan 2026)
        "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
        "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20",
        "2026-11-10", "2026-11-24", "2026-12-25",
    ])),
    settlement_holidays=frozenset(map(_d, [
        "2026-01-15",
        "2026-01-26", "2026-02-19", "2026-03-03", "2026-03-19", "2026-03-26", "2026-03-31",
        "2026-04-01", "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
        "2026-08-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
        "2026-12-25",
    ])),
    # Muhurat trading, Sunday 8 Nov 2026: own timetable (NSE/CMTR/76941), pre-open from 14:05; settles
    # 9 Nov 2026 as M 2026211 (NCL/CMPT/77037). Sunday stays a settlement holiday.
    special_timetable_opens=((_d("2026-11-08"), time(14, 5)),),
    # Union Budget, Sunday 1 Feb 2026: standard timings (pre-open 09:00-09:08, normal 09:15-15:30),
    # settled 2 Feb; 1 Feb itself was a settlement holiday (no T0 session).
    weekend_trading_days=frozenset({_d("2026-02-01")}),
    cites=(
        Cite(("NSE/CMTR/73927",), Status.PRIMARY, "15 weekday trading holidays for 2026 (section 2.1)."),
        Cite(("NCL/CMPT/71904",), Status.PRIMARY, "19 weekday settlement holidays for 2026."),
        Cite(("NSE/2026-01-15-HOLIDAY",), Status.SECONDARY,
             "15 Jan 2026 ad hoc trading and settlement holiday; NSE original not yet read."),
        Cite(("NSE/CMTR/72349", "NCL/CMPT/72384"), Status.PRIMARY,
             "Live trading session on Sunday 1 Feb 2026 at standard market timings; T+1 settlement 2 Feb 2026."),
        Cite(("NSE/CMTR/76941", "NCL/CMPT/77037"), Status.PRIMARY,
             "Muhurat session Sunday 8 Nov 2026 (14:05-16:00 incl. pre-open, CAS and post-close); trades settle "
             "9 Nov 2026."),
    ),
)

DEFAULT_YEARS: tuple[CalendarYear, ...] = (NSE_2026,)


class MarketCalendar:
    def __init__(self, years: tuple[CalendarYear, ...] = DEFAULT_YEARS) -> None:
        self._years: dict[tuple[Exchange, int], CalendarYear] = {}
        for y in years:
            key = (y.exchange, y.year)
            if key in self._years:
                raise ValueError(f"Duplicate calendar for {key}")
            for d in y.trading_holidays | y.settlement_holidays:
                if d.year != y.year:
                    raise ValueError(f"{d} is outside calendar year {y.year}")
                if d.weekday() >= 5:
                    raise ValueError(f"{d} is a weekend; list weekday holidays only")
            for d in y.weekend_trading_days:
                if d.year != y.year or d.weekday() < 5 or d in y.special_sessions:
                    raise ValueError(f"{d}: weekend trading days must be weekend dates in the year, not specials")
            opens = dict(y.special_timetable_opens)
            if len(opens) != len(y.special_timetable_opens):
                raise ValueError("Duplicate special timetable date")
            for d in opens:
                if (d.year != y.year or d in y.special_sessions or d in y.trading_holidays
                        or d in y.weekend_trading_days):
                    raise ValueError(f"{d}: a special timetable date must be in the year and not otherwise listed")
            self._years[key] = y

    def year(self, exchange: Exchange, d: date) -> CalendarYear:
        try:
            return self._years[(exchange, d.year)]
        except KeyError:
            raise RuleUnknown(f"No verified {exchange} calendar loaded for {d.year}") from None

    def covers(self, exchange: Exchange, d: date) -> bool:
        return (exchange, d.year) in self._years

    def is_special_session(self, exchange: Exchange, d: date) -> bool:
        """Any special session, whether or not its timetable is loaded (Budget Sunday is not special)."""
        y = self.year(exchange, d)
        return d in y.special_sessions or d in dict(y.special_timetable_opens)

    def has_special_timetable(self, exchange: Exchange, d: date) -> bool:
        return d in dict(self.year(exchange, d).special_timetable_opens)

    def is_trading_day(self, exchange: Exchange, d: date) -> bool:
        """Full trading day: a non-holiday weekday, or a weekend day the exchange runs with standard
        timings (e.g. Budget Sunday). Short special sessions with unknown timings (Muhurat) are not."""
        y = self.year(exchange, d)
        if d in y.weekend_trading_days or d in dict(y.special_timetable_opens):
            return True
        return d.weekday() < 5 and d not in y.trading_holidays and d not in y.special_sessions

    def session_open(self, exchange: Exchange, d: date) -> time | None:
        """Earliest order-entry time (pre-open start) of the day's session; None on a non-trading day."""
        y = self.year(exchange, d)
        if d in y.special_sessions:
            raise RuleUnknown(f"{d} is a special session whose timetable is not loaded")
        special = dict(y.special_timetable_opens)
        if d in special:
            return special[d]
        return REGULAR_OPEN if self.is_trading_day(exchange, d) else None

    def is_settlement_day(self, exchange: Exchange, d: date) -> bool:
        y = self.year(exchange, d)
        return d.weekday() < 5 and d not in y.settlement_holidays

    def next_trading_day(self, exchange: Exchange, d: date) -> date:
        n = d + timedelta(days=1)
        while not self.is_trading_day(exchange, n):
            n += timedelta(days=1)
        return n

    def previous_trading_day(self, exchange: Exchange, d: date) -> date:
        p = d - timedelta(days=1)
        while not self.is_trading_day(exchange, p):
            p -= timedelta(days=1)
        return p

    def settlement_date(self, exchange: Exchange, trade_date: date) -> date:
        """T+1: the first settlement working day strictly after the trade date.

        Derived from the T+1 rule plus the settlement-holiday list; NSE also publishes monthly
        settlement calendars, which should be loaded and compared once data ingestion exists.
        """
        if trade_date < T_PLUS_1_FROM:
            raise RuleUnknown("Settlement cycles before 27 Jan 2023 (phased T+2/T+1) are not modelled")
        n = trade_date + timedelta(days=1)
        while not self.is_settlement_day(exchange, n):
            n += timedelta(days=1)
        return n

    def is_first_trading_day_of_week(self, exchange: Exchange, d: date) -> bool:
        """'Every Monday / 1st trading day of the week' (GSM III/IV, IBC II once-a-week trading)."""
        if not self.is_trading_day(exchange, d):
            return False
        monday = d - timedelta(days=d.weekday())
        cur = monday
        while cur < d:
            if self.is_trading_day(exchange, cur):
                return False
            cur += timedelta(days=1)
        return True
