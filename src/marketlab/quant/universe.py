"""Dated universe screen U_D (spec section 3.1). Point-in-time: uses the previous session's bars and the
after-close rule files that describe session D. Reports what could not be verified instead of assuming."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .panel import Panel

V_MIN = 5 * 10_000_000  # Rs 5 crore median traded value over 20 sessions
LOOKBACK = 20


@dataclass(frozen=True, slots=True)
class ScreenPolicy:
    v_min: float = V_MIN
    lookback: int = LOOKBACK
    price_max_fraction: float = 0.5  # of W: at least one share fits a half-position
    W: float = 10_000.0
    min_band_pct: float = 10.0
    exclude_etfs: bool = True


@dataclass
class Screened:
    day: date
    isins: list[str]
    excluded: dict[str, str]
    unverified: list[str] = field(default_factory=list)  # e.g. SURVEILLANCE_UNVERIFIED, BAND_UNVERIFIED
    stats: dict = field(default_factory=dict)


def rule_inputs_for(market: Path, day: date, calendar=None) -> dict | None:
    """Next-session series, band and surveillance by (symbol) from the stored after-close files, or None."""
    from .. import sources
    from ..master import Inputs, parse_reg_indicators, parse_sec_list
    from ..rules.types import RuleUnknown
    if calendar is None:
        calendar = sources.load_calendar(market)[0]
    try:
        inp = Inputs(market, day, calendar)
    except RuleUnknown:
        return None
    out = {"series": {}, "band": {}, "reg": {}, "have_band": False, "have_reg": False}
    band_raw = inp.dated("nse_sec_list")
    if band_raw:
        out["have_band"] = True
        for (sym, ser), v in parse_sec_list(band_raw).items():
            out["series"][sym] = ser
            out["band"][sym] = None if v["band"] is None else float(v["band"])
    reg_raw = inp.dated("nse_reg_indicators")
    if reg_raw:
        out["have_reg"] = True
        for (sym, ser), v in parse_reg_indicators(reg_raw).items():
            out["reg"][sym] = v
            out["series"].setdefault(sym, ser)
    return out


def screen(panel: Panel, day: date, policy: ScreenPolicy = ScreenPolicy(), rule_inputs: dict | None = None,
           sessions: list[date] | None = None) -> Screened:
    """Universe for decisions made after the close of ``day`` (entries on the next session)."""
    sessions = sessions or panel.sessions()
    try:
        i = sessions.index(day)
    except ValueError:
        return Screened(day, [], {}, ["DAY_NOT_IN_PANEL"])
    window = sessions[max(0, i - policy.lookback + 1):i + 1]
    if len(window) < policy.lookback:
        return Screened(day, [], {}, ["INSUFFICIENT_HISTORY"])
    excluded, kept = {}, []
    unverified = []
    if rule_inputs is None or not rule_inputs.get("have_reg"):
        unverified.append("SURVEILLANCE_UNVERIFIED")
    if rule_inputs is None or not rule_inputs.get("have_band"):
        unverified.append("BAND_UNVERIFIED")
    today = {isin: b for isin, b in panel.cross_section(day)}
    counts = {}
    values: dict[str, list[float]] = {}
    for d in window:
        for isin, b in panel.cross_section(d):
            counts[isin] = counts.get(isin, 0) + (1 if b.volume > 0 else 0)
            values.setdefault(isin, []).append(b.value)
    for isin, b in today.items():
        sym = b.symbol
        series = (rule_inputs or {}).get("series", {}).get(sym, b.series)
        if series != "EQ":
            excluded[isin] = f"SERIES_{series}"
            continue
        if policy.exclude_etfs and panel.is_etf(isin):
            excluded[isin] = "ETF"
            continue
        if counts.get(isin, 0) < policy.lookback:
            excluded[isin] = "NOT_TRADED_EVERY_SESSION"
            continue
        vals = sorted(values[isin])
        med = vals[len(vals) // 2]
        if med < policy.v_min:
            excluded[isin] = "BELOW_V_MIN"
            continue
        if b.close > policy.price_max_fraction * policy.W:
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
    return Screened(day, sorted(kept), excluded, unverified, stats)
