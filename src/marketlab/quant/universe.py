"""Dated universe screen U_D (spec section 3.1). Point-in-time: bars up to the decision session D and the
after-close rule files that describe the ENTRY session (the exchange session after D). Reports what could not be
verified instead of assuming: missing rule files, a stored-data gap inside the lookback, reconstructed availability.

The screen is the opportunity set. It never looks at outcomes, so a security that is later suspended or delisted
stays in the universe of the days before that happened."""
from __future__ import annotations

import statistics

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .panel import Panel, is_etf_name

V_MIN = 5 * 10_000_000  # Rs 5 crore median traded value over 20 sessions
LOOKBACK = 20


@dataclass(frozen=True, slots=True)
class ScreenPolicy:
    v_min: float = V_MIN
    lookback: int = LOOKBACK
    price_max_fraction: float | None = 0.5  # of W: at least one share fits a half-position; None = analyse anyway
    W: float = 10_000.0
    min_band_pct: float = 10.0
    exclude_etfs: bool = True
    series: tuple[str, ...] = ("EQ",)  # BE (trade-for-trade, delivery only) is fine for a delivery investor


@dataclass
class Screened:
    day: date
    isins: list[str]
    excluded: dict[str, str]
    unverified: list[str] = field(default_factory=list)  # e.g. SURVEILLANCE_UNVERIFIED, BAND_UNVERIFIED
    stats: dict = field(default_factory=dict)
    median_value: dict = field(default_factory=dict)  # isin -> 20-session median traded value (slippage tier)
    availability: str = "NONE"  # RECEIPT | RECONSTRUCTED | NONE (rule inputs)

    @property
    def eligibility_verified(self) -> bool:
        return not self.unverified


def research_universe(panel: Panel, day: date, *, sessions: list[date] | None = None,
                      panel_days: set[date] | None = None) -> Screened:
    """Return every security present on ``day`` for prediction research.

    This is deliberately not an execution screen: price, turnover, trading
    frequency, surveillance, bands, auctions, and affordability do not remove
    a security. Those facts remain available for downstream eligibility and as
    model features where supported.
    """
    sessions = sessions or panel.sessions()
    panel_days = panel_days if panel_days is not None else set(panel.sessions())
    if day not in panel_days:
        return Screened(day, [], {}, ["DAY_NOT_IN_PANEL"], availability="NONE")
    today = {isin: b for isin, b in panel.cross_section(day)}
    if not today:
        return Screened(day, [], {}, ["NO_SECURITIES_ON_DAY"], availability="NONE")
    medians: dict[str, float] = {}
    try:
        i = sessions.index(day)
    except ValueError:
        return Screened(day, [], {}, ["DAY_NOT_IN_SESSIONS"], availability="NONE")
    window = sessions[max(0, i - 19):i + 1]
    for isin in today:
        values = [b.value for d in window for candidate, b in panel.cross_section(d)
                  if candidate == isin and b.value > 0]
        if values:
            medians[isin] = statistics.median(values[-20:])
    return Screened(
        day=day,
        isins=sorted(today),
        excluded={},
        unverified=[],
        stats={"kept": len(today), "research_universe": len(today)},
        median_value=medians,
        availability="NONE",
    )


def rule_inputs_for(market: Path, day: date, calendar=None, availability: str = "RECEIPT") -> dict | None:
    """Series, band and surveillance for session ``day`` (the entry session) from the after-close files of the
    previous session, or None.

    RECEIPT (forward decisions): only files this system received before the session opened.
    RECONSTRUCTED (historical replay, spec 2.1): files stored at any time (local receipt may be years later), admitted
    only when the server's Last-Modified time, recorded at receipt, is before ``day``'s session opens. A file without
    that evidence is not used: original availability unknown. Every result is labelled RECONSTRUCTED."""
    from datetime import datetime
    from .. import sources
    from ..common import IST, now, timestamp
    from ..master import Inputs, parse_reg_indicators, parse_sec_list
    from ..rules.types import Exchange, RuleUnknown
    if availability not in ("RECEIPT", "RECONSTRUCTED"):
        raise ValueError("availability must be RECEIPT or RECONSTRUCTED")
    if calendar is None:
        calendar = sources.load_calendar_for(market)[0]
    try:
        inp = Inputs(market, day, calendar, cutoff=now() if availability == "RECONSTRUCTED" else None)
    except RuleUnknown:
        return None
    out = {"series": {}, "band": {}, "reg": {}, "have_band": False, "have_reg": False, "availability": availability,
           "evidence": {}}
    opens = datetime.combine(day, calendar.session_open(Exchange.NSE, day), IST) if availability == "RECONSTRUCTED" else None

    def admissible(spec_id) -> bool:
        if availability != "RECONSTRUCTED":
            return True
        u = inp.used.get(spec_id) or {}
        ok = bool(u.get("published_at")) and timestamp(u["published_at"]) <= opens
        out["evidence"][spec_id] = {"server_last_modified": u.get("server_last_modified"), "admitted": ok}
        return ok
    band_raw = inp.dated("nse_sec_list")
    if band_raw and not admissible("nse_sec_list"):
        band_raw = None
    if band_raw:
        out["have_band"] = True
        for (sym, ser), v in parse_sec_list(band_raw).items():
            out["series"][sym] = ser
            out["band"][sym] = None if v["band"] is None else float(v["band"])
    reg_raw = inp.dated("nse_reg_indicators")
    if reg_raw and not admissible("nse_reg_indicators"):
        reg_raw = None
    if reg_raw:
        out["have_reg"] = True
        for (sym, ser), v in parse_reg_indicators(reg_raw).items():
            out["reg"][sym] = v
            out["series"].setdefault(sym, ser)
    return out


def screen_for_day(panel: Panel, day: date, policy: ScreenPolicy, market: Path, calendar,
                   availability: str = "RECEIPT") -> Screened:
    """The universe for decisions after the close of ``day``: exchange sessions from the calendar and the rule
    files of the entry session (the next exchange session), as the replay and the live decision use them."""
    from .sessions import exchange_sessions, next_session
    stored = set(panel.sessions())
    if not stored:
        return Screened(day, [], {}, ["PANEL_EMPTY"])
    sess = exchange_sessions(calendar, min(stored), max(stored), stored)[0]
    entry = next_session(calendar, day, sess)
    ri = rule_inputs_for(market, entry, calendar, availability) if entry else None
    return screen(panel, day, policy, ri, sess, stored)


def screen(panel: Panel, day: date, policy: ScreenPolicy = ScreenPolicy(), rule_inputs: dict | None = None,
           sessions: list[date] | None = None, panel_days: set[date] | None = None) -> Screened:
    """Universe for decisions made after the close of ``day`` (entries on the next session). ``sessions`` are
    exchange sessions; ``rule_inputs`` describe the entry session."""
    sessions = sessions or panel.sessions()
    panel_days = panel_days if panel_days is not None else set(panel.sessions())
    availability = (rule_inputs or {}).get("availability", "RECEIPT") if rule_inputs else "NONE"
    try:
        i = sessions.index(day)
    except ValueError:
        return Screened(day, [], {}, ["DAY_NOT_IN_PANEL"], availability=availability)
    if day not in panel_days:
        return Screened(day, [], {}, ["DAY_NOT_IN_PANEL"], availability=availability)
    window = sessions[max(0, i - policy.lookback + 1):i + 1]
    if len(window) < policy.lookback:
        return Screened(day, [], {}, ["INSUFFICIENT_HISTORY"], availability=availability)
    if any(d not in panel_days for d in window):
        return Screened(day, [], {}, ["PANEL_GAP_IN_LOOKBACK"], availability=availability)  # rule 2 unverifiable
    excluded, kept = {}, []
    unverified = []
    if rule_inputs is None or not rule_inputs.get("have_reg"):
        unverified.append("SURVEILLANCE_UNVERIFIED")
    if rule_inputs is None or not rule_inputs.get("have_band"):
        unverified.append("BAND_UNVERIFIED")
    today = {isin: b for isin, b in panel.cross_section(day)}
    names = panel.names_on(day)
    medians: dict[str, float] = {}
    counts = {}
    values: dict[str, list[float]] = {}
    for d in window:
        for isin, b in panel.cross_section(d):
            counts[isin] = counts.get(isin, 0) + (1 if b.volume > 0 else 0)
            values.setdefault(isin, []).append(b.value)
    for isin, b in today.items():
        sym = b.symbol
        series = (rule_inputs or {}).get("series", {}).get(sym, b.series)
        if series not in policy.series:
            excluded[isin] = f"SERIES_{series}"
            continue
        if policy.exclude_etfs and is_etf_name(isin, names.get(isin)):  # the name printed on that day
            excluded[isin] = "ETF"
            continue
        if counts.get(isin, 0) < policy.lookback:
            excluded[isin] = "NOT_TRADED_EVERY_SESSION"
            continue
        vals = sorted(values[isin])
        med = statistics.median(vals)  # an even count averages the middle pair (audit finding 2026-11-07)
        medians[isin] = med
        if med < policy.v_min:
            excluded[isin] = "BELOW_V_MIN"
            continue
        if policy.price_max_fraction is not None and b.close > policy.price_max_fraction * policy.W:
            excluded[isin] = "PRICE_ABOVE_HALF_POSITION"
            continue
        reg = (rule_inputs or {}).get("reg", {}).get(sym)
        if reg:
            if reg.get("suspended"):
                excluded[isin] = "SUSPENDED"
                continue
            if reg.get("call_auction"):
                excluded[isin] = "PERIODIC_CALL_AUCTION"
                continue
            if reg.get("surveillance") is None:
                excluded[isin] = "SURVEILLANCE_UNKNOWN"
                continue
            if reg["surveillance"]:
                excluded[isin] = "UNDER_SURVEILLANCE"
                continue
        band = (rule_inputs or {}).get("band", {}).get(sym, "absent")
        if band != "absent" and band is not None and band < policy.min_band_pct:
            excluded[isin] = f"BAND_{band:g}"
            continue
        kept.append(isin)
    from collections import Counter
    stats = dict(Counter(excluded.values()))
    stats["kept"] = len(kept)
    return Screened(day, sorted(kept), excluded, unverified, stats, {i: medians[i] for i in kept}, availability)
