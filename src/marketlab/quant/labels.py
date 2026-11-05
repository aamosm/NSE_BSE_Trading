"""Forward-return labels (spec sections 2.2, 2.4, 4.1): open of D+1 to open of D+h+1 over exchange sessions.

Labels are GROSS market quantities: actual traded opens, divided by exchange-implied factors of listed actions,
minus the benchmark's open-to-open log return. They contain no slippage and no charges. Slippage and charges are
counted exactly once, by the allocator ex ante (at the whole-share quantity) and by the ledger ex post (at the
actual fills); spec 2.5 says "only gross quantities are modelled, costs are subtracted by the allocator".

A label is RESOLVED, UNRESOLVED (its exit session is beyond the data the caller may see) or EXCLUDED with a
reason. Exclusions are statistical: they keep a row out of fitting and calibration metrics. They never remove
the opportunity from the decision-time universe; the paper ledger handles a missing or blocked exit itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from .panel import Panel
from .sessions import _index

LIQUID_VALUE = 10 * 10_000_000  # Rs 10 crore: slippage 0.10% at or above, 0.25% below (spec section 2.2)
SLIPPAGE_LIQUID, SLIPPAGE_OTHER = 0.0010, 0.0025
UNEXPLAINED_FACTOR_TOLERANCE = 0.0005

RESOLVED, UNRESOLVED, EXCLUDED = "RESOLVED", "UNRESOLVED", "EXCLUDED"


@dataclass(frozen=True, slots=True)
class Label:
    isin: str
    decision_day: date
    entry_day: date | None
    exit_day: date | None
    h: int
    status: str
    reason: str | None
    entry_open: float = float("nan")  # actual traded opens, no slippage
    exit_open: float = float("nan")
    factor: float = 1.0  # product of applied (listed) implied factors in (entry_day, exit_day]
    gross: float = float("nan")  # simple return (exit_open / factor) / entry_open - 1
    gross_log: float = float("nan")
    index_log: float | None = None  # benchmark open-to-open log return
    excess: float | None = None  # gross_log - index_log (the model target, spec 4.1)
    basis: str = "UNKNOWN"  # VERIFIED (no adjustment needed) | RECONSTRUCTED (listed action applied) | UNKNOWN

    @property
    def excluded(self) -> str | None:
        return self.reason if self.status == EXCLUDED else None


def slippage_for(median_value_20: float) -> float:
    return SLIPPAGE_LIQUID if median_value_20 >= LIQUID_VALUE else SLIPPAGE_OTHER


def forward_return(panel: Panel, isin: str, decision_day: date, h: int, *, sessions: list[date],
                   panel_days: set[date] | None = None, index_name: str = "Nifty 50",
                   listed_action_days: set[date] | None = None, data: dict | None = None) -> Label:
    """Label for a decision after the close of ``decision_day``. ``sessions`` are exchange sessions (calendar),
    truncated at the last session the caller may see; ``panel_days`` the sessions actually stored. ``data`` may
    carry the security's preloaded {"bars": {day: Bar}, "factors": {day: f}} and the panel-wide "unchecked" set
    and "index" levels (the batch path); the result is identical to the queried path."""
    panel_days = panel_days if panel_days is not None else set(panel.sessions())
    i = _index(sessions, decision_day)
    if i is None:
        return Label(isin, decision_day, None, None, h, EXCLUDED, "NOT_A_SESSION")
    if i + h + 1 >= len(sessions):
        return Label(isin, decision_day, None, None, h, UNRESOLVED, "EXIT_BEYOND_DATA")
    entry_day, exit_day = sessions[i + 1], sessions[i + h + 1]
    window = sessions[i + 1:i + h + 2]

    def out(status, reason, **kw):
        return Label(isin, decision_day, entry_day, exit_day, h, status, reason, **kw)

    if any(d not in panel_days for d in window):
        return out(EXCLUDED, "DATA_GAP")  # the horizon is never stretched over a missing session
    bars = data["bars"] if data else {b.day: b for b in panel.bars(isin, entry_day, exit_day)}
    eb, xb = bars.get(entry_day), bars.get(exit_day)
    ends = data.get("disc", {}) if data else panel.discontinuities(isin, entry_day, exit_day)
    if eb is None or not (eb.open > 0) or not (eb.volume > 0):
        return out(EXCLUDED, "NO_TRADE_AT_ENTRY")
    if xb is None or not (xb.open > 0) or not (xb.volume > 0):
        if any(k == "IDENTITY_END" for d, v in ends.items() if entry_day < d <= exit_day for k, _, _ in v):
            return out(EXCLUDED, "IDENTITY_CHANGE")  # the ISIN was replaced (usually a split): not a suspension
        return out(EXCLUDED, "NO_TRADE_AT_EXIT")
    if data:
        unchecked = any(d in data["unchecked"] for d in sessions[i + 2:i + h + 2])
        found = {d: f for d, f in data["factors"].items() if entry_day <= d <= exit_day}
        disc = {d: v for d, v in data.get("disc", {}).items() if entry_day < d <= exit_day}
    else:
        unchecked = bool(panel.unchecked_days(sessions[i + 2], exit_day))
        found = panel.implied_factors(isin, entry_day, exit_day)
        disc = {d: v for d, v in panel.discontinuities(isin, entry_day, exit_day).items() if d > entry_day}
    if unchecked:  # (entry, exit]: an ex-date there could not be checked
        return out(EXCLUDED, "ACTION_COVERAGE_UNKNOWN")
    if any(k == "PRICE_DISCONTINUITY" for v in disc.values() for k, _, _ in v):
        # the base price is not adjusted on ex-dates, so an action is a price jump of unknown ratio: no label
        return out(EXCLUDED, "PRICE_DISCONTINUITY_UNEXPLAINED")
    factor, basis = 1.0, "VERIFIED"
    for d, f in sorted(found.items()):
        if d == entry_day:  # the entry bar's own base price is before our entry at the open
            continue
        if abs(f - 1) <= UNEXPLAINED_FACTOR_TOLERANCE:
            continue
        if listed_action_days is None or d not in listed_action_days:
            return out(EXCLUDED, "UNEXPLAINED_PRICE_ADJUSTMENT")  # spec 2.4: excluded and counted
        factor *= f
        basis = "RECONSTRUCTED"
    gross = (xb.open / factor) / eb.open - 1
    gl = math.log1p(gross)
    idx = data["index"] if data else panel.index_levels(index_name, entry_day, exit_day)
    if not (entry_day in idx and exit_day in idx and (idx[entry_day][0] or 0) > 0 and (idx[exit_day][0] or 0) > 0):
        return out(EXCLUDED, "NO_BENCHMARK", entry_open=eb.open, exit_open=xb.open, factor=factor, gross=gross,
                   gross_log=gl, basis=basis)
    il = math.log(idx[exit_day][0] / idx[entry_day][0])
    return out(RESOLVED, None, entry_open=eb.open, exit_open=xb.open, factor=factor, gross=gross, gross_log=gl,
               index_log=il, excess=gl - il, basis=basis)


def label_end_index(decision_index: int, h: int) -> int:
    """Session index of the label's end (the exit open), used for purging: decision i -> exit at i + h + 1."""
    return decision_index + h + 1
