"""Exchange sessions for replay: the loaded calendar, not the rows that happen to be stored.

A horizon of h sessions counts exchange sessions. A session the calendar says existed but the panel does not hold
is a data gap: labels and fills that need it are unknown, never stretched over the next stored row. A year the
calendar does not cover falls back to the panel's own days and is reported as PANEL_ONLY (unverified sessions;
such periods cannot support promotion).
"""
from __future__ import annotations

from datetime import date, timedelta

from ..rules.types import Exchange, RuleUnknown


def exchange_sessions(calendar, start: date, end: date, panel_days: set[date]) -> tuple[list[date], dict[int, str]]:
    """(sessions in [start, end], {year: CALENDAR | OBSERVED_PUBLICATION | PANEL_ONLY}). A calendar may declare its
    own ``basis`` (e.g. history.ObservedCalendar: sessions reconstructed from what the exchange published)."""
    out, basis = [], {}
    label = getattr(calendar, "basis", "CALENDAR")
    per_day = getattr(calendar, "basis_for", None)
    d = start
    while d <= end:
        covered = calendar.covers(Exchange.NSE, d)
        if covered:
            try:
                ok = calendar.is_trading_day(Exchange.NSE, d) or calendar.is_special_session(Exchange.NSE, d)
            except RuleUnknown:
                ok = d in panel_days
            basis.setdefault(d.year, per_day(d) if per_day else label)
        else:
            ok = d in panel_days
            basis[d.year] = "PANEL_ONLY"
        if ok:
            out.append(d)
        d += timedelta(days=1)
    return out, basis


def next_session(calendar, d: date, sessions: list[date] | None = None) -> date | None:
    """The exchange session after ``d`` (from ``sessions`` when it extends past d, else the calendar)."""
    if sessions:
        i = _index(sessions, d)
        if i is not None and i + 1 < len(sessions):
            return sessions[i + 1]
    try:
        if calendar.covers(Exchange.NSE, d + timedelta(days=1)):
            return calendar.next_trading_day(Exchange.NSE, d)
    except RuleUnknown:
        return None
    return None


def _index(sessions: list[date], d: date) -> int | None:
    import bisect
    i = bisect.bisect_left(sessions, d)
    return i if i < len(sessions) and sessions[i] == d else None


def settlement_lag_sessions(trade_day: date) -> int:
    """Sessions until sale proceeds may fund a new order: T+1 from 27 Jan 2023 (spec 6), conservatively T+2 before
    (the T+1 phase-in ran from Feb 2022 to Jan 2023 by market capitalisation)."""
    from ..rules.calendar import T_PLUS_1_FROM
    return 1 if trade_day >= T_PLUS_1_FROM else 2
