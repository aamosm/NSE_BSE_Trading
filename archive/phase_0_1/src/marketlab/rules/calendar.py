"""Trading and settlement calendars.

Only years whose holiday lists were read from an official source are loaded. Any date
outside a loaded year raises ``RuleUnknown`` so that replay over unloaded history fails
loudly instead of silently treating every weekday as a trading day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .provenance import Cite, Status
from .types import Exchange, RuleUnknown

T_PLUS_1_FROM = date(2023, 1, 27)
T_PLUS_1_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                     "All securities moved to T+1 rolling settlement effective 27 Jan 2023 (section 1.5).")


@dataclass(frozen=True, slots=True)
class CalendarYear:
    exchange: Exchange
    year: int
    trading_holidays: frozenset[date]  # weekday closures
    settlement_holidays: frozenset[date]  # weekday settlement closures (superset of most trading holidays)
    special_sessions: frozenset[date] = frozenset()  # weekend sessions (e.g. Muhurat); timings separate
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
    special_sessions=frozenset({_d("2026-11-08")}),  # Muhurat trading (Sunday); timings not yet notified
    cites=(
        Cite(("NSE/CMTR/73927",), Status.PRIMARY, "15 weekday trading holidays for 2026 (section 2.1)."),
        Cite(("NCL/CMPT/71904",), Status.PRIMARY, "19 weekday settlement holidays for 2026."),
        Cite(("NSE/2026-01-15-HOLIDAY",), Status.SECONDARY,
             "15 Jan 2026 ad hoc trading and settlement holiday; NSE original not yet read."),
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
            self._years[key] = y

    def year(self, exchange: Exchange, d: date) -> CalendarYear:
        try:
            return self._years[(exchange, d.year)]
        except KeyError:
            raise RuleUnknown(f"No verified {exchange} calendar loaded for {d.year}") from None

    def covers(self, exchange: Exchange, d: date) -> bool:
        return (exchange, d.year) in self._years

    def is_special_session(self, exchange: Exchange, d: date) -> bool:
        return d in self.year(exchange, d).special_sessions

    def is_trading_day(self, exchange: Exchange, d: date) -> bool:
        """Regular trading day. Weekend special sessions (Muhurat) return False here."""
        y = self.year(exchange, d)
        return d.weekday() < 5 and d not in y.trading_holidays

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
