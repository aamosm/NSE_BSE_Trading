"""Exchange session timetable for the equity cash market (normal market, regular trading days).

Effective-dated regimes:
* Pre-open V1 (until 2026-09-06): 09:00-09:08 order entry, random close in the 8th minute.
* Pre-open V2 (from 2026-09-07): 09:00-09:05 limit+market, 09:05-09:10 limit only, random close
  09:08-09:10, matching 09:10-09:12, buffer to 09:15.
* Close V1 (until 2026-08-02): continuous to 15:30, post-close 15:40-16:00.
* Close V2 (from 2026-08-03): F&O stocks stop continuous trading at 15:15 and close through the
  Closing Auction Session (CAS) 15:15-15:35; other stocks trade continuously to 15:30. Post-close
  15:50-16:00.

Random-closure windows are treated as *not accepting* new orders, because acceptance is not
guaranteed. Special sessions use only their own circular's table (``SPECIAL_TIMETABLES``); a special
session without a loaded table raises ``RuleUnknown``. IPO/relisting special pre-open and periodic
call auctions are out of scope and are rejected by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from .calendar import T_PLUS_1_FROM, MarketCalendar
from .provenance import Cite, Status
from .types import IST, Exchange, OrderType, RuleUnknown

CAS_FROM = date(2026, 8, 3)
PREOPEN_V2_FROM = date(2026, 9, 7)


class SessionKind(StrEnum):
    CLOSED = "CLOSED"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    PRE_OPEN_ALL = "PRE_OPEN_ALL"  # limit and market orders
    PRE_OPEN_LIMIT_ONLY = "PRE_OPEN_LIMIT_ONLY"
    PRE_OPEN_RANDOM_CLOSE = "PRE_OPEN_RANDOM_CLOSE"
    PRE_OPEN_MATCHING = "PRE_OPEN_MATCHING"  # matching + buffer; no entry
    CONTINUOUS = "CONTINUOUS"
    CAS_TRANSITION = "CAS_TRANSITION"  # 15:15-15:20 reference price; no exchange entry
    CAS_ALL = "CAS_ALL"
    CAS_LIMIT_ONLY = "CAS_LIMIT_ONLY"
    CAS_RANDOM_CLOSE = "CAS_RANDOM_CLOSE"
    CAS_MATCHING = "CAS_MATCHING"
    POST_CLOSE = "POST_CLOSE"  # market orders only, executed at the day's closing price


ACCEPTED_ORDER_TYPES: dict[SessionKind, frozenset[OrderType]] = {
    SessionKind.PRE_OPEN_ALL: frozenset({OrderType.LIMIT, OrderType.MARKET}),
    SessionKind.PRE_OPEN_LIMIT_ONLY: frozenset({OrderType.LIMIT}),
    SessionKind.CONTINUOUS: frozenset({OrderType.LIMIT, OrderType.MARKET, OrderType.SL, OrderType.SL_M}),
    SessionKind.CAS_ALL: frozenset({OrderType.LIMIT, OrderType.MARKET}),
    SessionKind.CAS_LIMIT_ONLY: frozenset({OrderType.LIMIT}),
    SessionKind.POST_CLOSE: frozenset({OrderType.MARKET}),
}

AUCTION_SESSIONS = frozenset({
    SessionKind.PRE_OPEN_ALL, SessionKind.PRE_OPEN_LIMIT_ONLY, SessionKind.CAS_ALL, SessionKind.CAS_LIMIT_ONLY,
})

SESSION_CITES: dict[str, Cite] = {
    "preopen_v1": Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                       "09:00-09:08 entry (random close 7th-8th minute), limit and market allowed (section 1.1)."),
    "preopen_v2": Cite(("NSE/CMTR/74969", "SEBI/CAS-2026"), Status.PRIMARY,
                       "From 7 Sep 2026: 09:00-09:05 limit+market, 09:05-09:10 limit only, random close in last "
                       "2 minutes; SL/IOC/DQ not allowed."),
    "preopen_sl_v1": Cite(("NSE/CMTR/73927",), Status.ASSUMPTION,
                          "V1 text lists limit and market only; SL treated as not allowed in pre-open."),
    "continuous": Cite(("NSE/CMTR/73927",), Status.PRIMARY, "Normal market 09:15-15:30 (section 2.2)."),
    "post_close_v1": Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                          "Closing session 15:40-16:00, market orders only at close price (section 1.8)."),
    "cas": Cite(("SEBI/CAS-2026", "NSE/CMTR/73362"), Status.PRIMARY,
                "From 3 Aug 2026 for stocks with derivatives: CAS 15:15-15:35; 15:20-15:25 limit+market; "
                "15:25-15:30 limit only, random close 15:28-15:30; matching 15:30-15:35; no SL orders."),
    "post_close_v2": Cite(("SEBI/CAS-2026",), Status.PRIMARY, "Post-close session 15:50-16:00 from 3 Aug 2026."),
}


@dataclass(frozen=True, slots=True)
class Window:
    kind: SessionKind
    start: time
    end: time  # exclusive


def _t(s: str) -> time:
    return time.fromisoformat(s)


def _preopen(d: date) -> list[Window]:
    if d >= PREOPEN_V2_FROM:
        return [
            Window(SessionKind.PRE_OPEN_ALL, _t("09:00"), _t("09:05")),
            Window(SessionKind.PRE_OPEN_LIMIT_ONLY, _t("09:05"), _t("09:08")),
            Window(SessionKind.PRE_OPEN_RANDOM_CLOSE, _t("09:08"), _t("09:10")),
            Window(SessionKind.PRE_OPEN_MATCHING, _t("09:10"), _t("09:15")),
        ]
    return [
        Window(SessionKind.PRE_OPEN_ALL, _t("09:00"), _t("09:07")),
        Window(SessionKind.PRE_OPEN_RANDOM_CLOSE, _t("09:07"), _t("09:08")),
        Window(SessionKind.PRE_OPEN_MATCHING, _t("09:08"), _t("09:15")),
    ]


def _close(d: date, cas_applies: bool) -> list[Window]:
    if d < CAS_FROM:
        return [
            Window(SessionKind.CONTINUOUS, _t("09:15"), _t("15:30")),
            Window(SessionKind.CLOSED, _t("15:30"), _t("15:40")),
            Window(SessionKind.POST_CLOSE, _t("15:40"), _t("16:00")),
        ]
    if not cas_applies:
        return [
            Window(SessionKind.CONTINUOUS, _t("09:15"), _t("15:30")),
            Window(SessionKind.CLOSED, _t("15:30"), _t("15:50")),
            Window(SessionKind.POST_CLOSE, _t("15:50"), _t("16:00")),
        ]
    return [
        Window(SessionKind.CONTINUOUS, _t("09:15"), _t("15:15")),
        Window(SessionKind.CAS_TRANSITION, _t("15:15"), _t("15:20")),
        Window(SessionKind.CAS_ALL, _t("15:20"), _t("15:25")),
        Window(SessionKind.CAS_LIMIT_ONLY, _t("15:25"), _t("15:28")),
        Window(SessionKind.CAS_RANDOM_CLOSE, _t("15:28"), _t("15:30")),
        Window(SessionKind.CAS_MATCHING, _t("15:30"), _t("15:35")),
        Window(SessionKind.CLOSED, _t("15:35"), _t("15:50")),
        Window(SessionKind.POST_CLOSE, _t("15:50"), _t("16:00")),
    ]


def _muhurat_2026(cas: bool) -> list[Window]:
    """NSE/CMTR/76941, Sunday 8 Nov 2026. Random closure in the last 2 minutes of each entry period."""
    pre = [
        Window(SessionKind.PRE_OPEN_ALL, _t("14:05"), _t("14:10")),
        Window(SessionKind.PRE_OPEN_LIMIT_ONLY, _t("14:10"), _t("14:13")),
        Window(SessionKind.PRE_OPEN_RANDOM_CLOSE, _t("14:13"), _t("14:15")),
        Window(SessionKind.PRE_OPEN_MATCHING, _t("14:15"), _t("14:20")),  # matching 14:15-14:17, buffer to 14:20
    ]
    if not cas:
        return pre + [
            Window(SessionKind.CONTINUOUS, _t("14:20"), _t("15:30")),
            Window(SessionKind.CLOSED, _t("15:30"), _t("15:50")),
            Window(SessionKind.POST_CLOSE, _t("15:50"), _t("16:00")),
        ]
    return pre + [
        Window(SessionKind.CONTINUOUS, _t("14:20"), _t("15:15")),
        Window(SessionKind.CAS_TRANSITION, _t("15:15"), _t("15:20")),
        Window(SessionKind.CAS_ALL, _t("15:20"), _t("15:25")),
        Window(SessionKind.CAS_LIMIT_ONLY, _t("15:25"), _t("15:28")),
        Window(SessionKind.CAS_RANDOM_CLOSE, _t("15:28"), _t("15:30")),
        Window(SessionKind.CAS_MATCHING, _t("15:30"), _t("15:35")),
        Window(SessionKind.CLOSED, _t("15:35"), _t("15:50")),
        Window(SessionKind.POST_CLOSE, _t("15:50"), _t("16:00")),
    ]


SPECIAL_TIMETABLES = {
    (Exchange.NSE, date(2026, 11, 8)): _muhurat_2026,
}
SESSION_CITES["muhurat_2026"] = Cite(("NSE/CMTR/76941",), Status.PRIMARY,
                                     "Muhurat 8 Nov 2026: block deal 13:50-14:05; pre-open 14:05-14:15 (limit and "
                                     "market to 14:10, limit only to 14:15); normal market 14:20-15:30 (15:15 for "
                                     "CAS stocks); CAS 15:15-15:35; post-close 15:50-16:00.")


def cas_applies(d: date, has_derivatives: bool | None) -> bool:
    if d < CAS_FROM:
        return False
    if has_derivatives is None:
        raise RuleUnknown("Whether the stock has derivatives is unknown, so CAS applicability is unknown")
    return has_derivatives


def timetable(d: date, has_derivatives: bool | None) -> tuple[Window, ...]:
    if d < T_PLUS_1_FROM:
        raise RuleUnknown("Session timetables before 27 Jan 2023 are not modelled")
    return tuple(_preopen(d) + _close(d, cas_applies(d, has_derivatives)))


def session_at(ts: datetime, exchange: Exchange, has_derivatives: bool | None,
               calendar: MarketCalendar) -> SessionKind:
    if ts.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    local = ts.astimezone(IST)
    d, t = local.date(), local.time()
    if calendar.has_special_timetable(exchange, d):
        build = SPECIAL_TIMETABLES.get((exchange, d))
        if build is None:
            raise RuleUnknown(f"{d}: special session timetable missing from rules.sessions")
        windows = tuple(build(cas_applies(d, has_derivatives)))
    elif calendar.is_special_session(exchange, d):
        raise RuleUnknown(f"{d} is a special session; its timetable is not loaded")
    elif not calendar.is_trading_day(exchange, d):
        return SessionKind.NON_TRADING_DAY
    else:
        windows = timetable(d, has_derivatives)
    for w in windows:
        if w.start <= t < w.end:
            return w.kind
    return SessionKind.CLOSED
