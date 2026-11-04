"""Forward-return labels (spec section 2): open of D+1 to open of D+h+1, slippage, exchange-implied factors."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from .panel import Panel

LIQUID_VALUE = 10 * 10_000_000  # Rs 10 crore: slippage 0.10% at or above, 0.25% below (spec section 2.2)
SLIPPAGE_LIQUID, SLIPPAGE_OTHER = 0.0010, 0.0025
UNEXPLAINED_FACTOR_TOLERANCE = 0.0005


@dataclass(frozen=True, slots=True)
class Label:
    isin: str
    decision_day: date
    entry_day: date
    exit_day: date
    h: int
    entry_price: float  # effective, after slippage
    exit_price: float  # effective, after slippage, before factor division
    factor: float  # product of implied factors in (entry_day, exit_day]
    gross: float  # simple return
    gross_log: float
    excess: float | None  # gross log return minus the benchmark open-to-open log return; None when the index is missing
    excluded: str | None  # reason, or None


def slippage_for(median_value_20: float) -> float:
    return SLIPPAGE_LIQUID if median_value_20 >= LIQUID_VALUE else SLIPPAGE_OTHER


def forward_return(panel: Panel, isin: str, decision_day: date, h: int, *, sessions: list[date] | None = None,
                   s_in: float | None = None, s_out: float | None = None, index_name: str = "Nifty 50",
                   listed_action_days: set[date] | None = None) -> Label | None:
    """Label for a decision after the close of ``decision_day``: entry at the next session's open, exit at the open
    h+1 sessions later. Returns None when the sessions do not exist yet (label not resolved)."""
    sessions = sessions or panel.sessions()
    try:
        i = sessions.index(decision_day)
    except ValueError:
        return None
    if i + h + 1 >= len(sessions):
        return None
    entry_day, exit_day = sessions[i + 1], sessions[i + h + 1]
    bars = {b.day: b for b in panel.bars(isin, entry_day, exit_day)}
    eb, xb = bars.get(entry_day), bars.get(exit_day)
    if eb is None or xb is None or not (eb.open > 0 and xb.open > 0):
        return _excluded(isin, decision_day, entry_day, exit_day, h, "NO_TRADE_AT_ENTRY_OR_EXIT")
    recent = panel.bars(isin, sessions[max(0, i - 19)], decision_day)
    med = sorted(b.value for b in recent)[len(recent) // 2] if recent else 0.0
    s_in = slippage_for(med) if s_in is None else s_in
    s_out = slippage_for(med) if s_out is None else s_out
    factors = panel.implied_factors(isin, entry_day, exit_day)
    factor = 1.0
    for d, f in factors.items():
        if d == entry_day:  # the entry bar's own base price is before our entry at the open; factor applies after
            continue
        if listed_action_days is not None and d not in listed_action_days and abs(f - 1) > UNEXPLAINED_FACTOR_TOLERANCE:
            return _excluded(isin, decision_day, entry_day, exit_day, h, "UNEXPLAINED_PRICE_ADJUSTMENT")
        factor *= f
    pe = eb.open * (1 + s_in)
    px = xb.open * (1 - s_out)
    gross = (px / factor) / pe - 1
    gl = math.log1p(gross)
    idx = panel.index_levels(index_name, entry_day, exit_day)
    excess = None
    if entry_day in idx and exit_day in idx and idx[entry_day][0] > 0 and idx[exit_day][0] > 0:
        excess = gl - math.log(idx[exit_day][0] / idx[entry_day][0])
    return Label(isin, decision_day, entry_day, exit_day, h, pe, px, factor, gross, gl, excess, None)


def _excluded(isin, d, e, x, h, reason) -> Label:
    return Label(isin, d, e, x, h, float("nan"), float("nan"), 1.0, float("nan"), float("nan"), None, reason)


def label_end_index(decision_index: int, h: int) -> int:
    """Session index of the label's end (the exit open), used for purging: decision i -> exit at i + h + 1."""
    return decision_index + h + 1
