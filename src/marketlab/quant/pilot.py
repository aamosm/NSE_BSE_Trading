"""Historical pilot analysis: coverage by horizon, admissible labels and folds, corporate-action evidence,
ledger traces and the reconstructed Infosys Q4 FY25 case.

Everything here reads stored official files only. Nothing invents a past forecast: a trace made without a
contemporary forecast is labelled RECONSTRUCTED_NO_FORECAST and shows mechanics (availability, eligibility, fills,
costs, benchmark), never a claim that the system would have chosen the trade.
"""
from __future__ import annotations

import html as _html
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from ..common import IST
from ..rules.types import Exchange, RuleUnknown
from . import allocate, evaluate, labels
from .ledger import ExecutionPolicy, Intent, Ledger, money, reservation
from .panel import Panel
from .sessions import exchange_sessions
from .universe import ScreenPolicy, rule_inputs_for, screen

HORIZONS = (5, 20, 60)


# ---- filings -----------------------------------------------------------------------------------------------

def filing_rows(doc: bytes) -> list[list[str]]:
    text = doc.decode("utf-8", "replace")
    out = []
    for r in re.findall(r"<tr\b.*?</tr>", text, flags=re.S | re.I):
        cells = [_html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<t[hd]\b.*?</t[hd]>", r, flags=re.S | re.I)]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out


def filing_fields(doc: bytes) -> dict:
    """General information and the first Ind-AS results table (quarter column, year-to-date column), with the
    presentation unit and rounding level read from the filing itself."""
    rows = filing_rows(doc)
    info, fin = {}, {}
    in_results = False
    for cells in rows:
        if cells[0] == "Financial Results Ind-AS":
            in_results = True
        elif cells[0].startswith("Statement of Asset"):
            in_results = False
        if len(cells) == 2 and not in_results:
            info.setdefault(cells[0], cells[1])
        if in_results:
            label = cells[1] if (len(cells) >= 3 and re.fullmatch(r"[A-Za-z0-9()]{1,4}|[0-9]+", cells[0])) else cells[0]
            vals = [c for c in cells[1:] if c != label]
            if vals and label not in fin:
                fin[label] = vals
    unit = info.get("Description of presentation currency", "")
    rounding = info.get("Level of rounding used in financial results", "")

    def amount(label, col=0):
        v = fin.get(label)
        try:
            return float(v[col]) if v else None
        except (ValueError, IndexError):
            return None
    rev = amount("Revenue from operations")
    return {"symbol": info.get("NSE Symbol"), "isin": info.get("ISIN"), "company": info.get("Name of company"),
            "basis": fin.get("Nature of report standalone or consolidated", [None])[0],
            "audited": fin.get("Whether results are audited or unaudited", [None])[0],
            "period": [fin.get("Date of start of reporting period", [None])[0], fin.get("Date of end of reporting period", [None])[0]],
            "presentation_unit": unit, "rounding_level": rounding,
            "board_meeting": [info.get("Start date and time of board meeting"), info.get("End date and time of board meeting")],
            "prior_intimation_date": info.get("Date on which prior intimation of the meeting for considering financial results "
                                              "was informed to the exchange"),
            "revenue_from_operations_inr": rev, "net_profit_inr": amount("Total profit (loss) for period"),
            "profit_attributable_to_owners_inr": amount("Profit or loss, attributable to owners of parent"),
            "basic_eps_inr": amount("Basic earnings (loss) per share from continuing and discontinued operations"),
            "revenue_from_operations_crore": rev / 1e7 if rev is not None and "Actual" in unit else None}


def check_amount(fields: dict, claimed_value: float, claimed_unit: str) -> bool:
    """Does a claimed figure match the filing once its unit is applied? (an INR-actuals amount read as crores fails)"""
    actual = fields["revenue_from_operations_inr"]
    scale = {"INR": 1.0, "crore": 1e7, "lakh": 1e5, "million": 1e6}[claimed_unit]
    return actual is not None and "Actual" in fields["presentation_unit"] and abs(claimed_value * scale - actual) < 0.5 * 1e7


# ---- coverage, labels, folds -----------------------------------------------------------------------------------

def universes(view: Panel, sessions: list[date], stored: set[date], market: Path, calendar, policy: ScreenPolicy) -> dict:
    out = {}
    for k, d in enumerate(sessions):
        if d not in stored:
            continue
        entry = sessions[k + 1] if k + 1 < len(sessions) else None
        ri = rule_inputs_for(market, entry, calendar, "RECONSTRUCTED") if entry else None
        out[d] = screen(view, d, policy, ri, sessions, stored)
    return out


def coverage(view: Panel, calendar, market: Path, start: date, end: date, *, policy: ScreenPolicy, horizons=HORIZONS,
             index_name="Nifty 50", progress=None) -> dict:
    stored = set(view.sessions(start, end))
    sessions, basis = exchange_sessions(calendar, start, end, stored)
    unis = universes(view, sessions, stored, market, calendar, policy)
    isins = sorted({i for u in unis.values() for i in u.isins})
    unchecked, index = view.unchecked_days(), view.index_levels(index_name)
    data = {i: {"bars": {b.day: b for b in view.bars(i)}, "factors": view.implied_factors(i), "unchecked": unchecked,
                "index": index, "disc": view.discontinuities(i)} for i in isins}
    days_verified = [d for d, u in unis.items() if u.isins and not u.unverified]
    out = {"expected_sessions": len(sessions), "stored_sessions": len(stored), "missing_sessions": [d.isoformat() for d in sessions if d not in stored],
           "session_basis": {str(k): v for k, v in basis.items()},
           "decision_days": len(unis), "decision_days_with_universe": sum(1 for u in unis.values() if u.isins),
           "decision_days_eligibility_verified": len(days_verified),
           "unverified_reasons": _count(r for u in unis.values() for r in u.unverified),
           "universe_size_median": __import__("statistics").median(len(u.isins) for u in unis.values()) if unis else 0,
           "horizons": {}}
    for h in horizons:
        counts, admissible, first, last = {}, 0, None, None
        for d, u in unis.items():
            for i in u.isins:
                lab = labels.forward_return(view, i, d, h, sessions=sessions, panel_days=stored, index_name=index_name, data=data[i])
                key = lab.status if lab.status == labels.RESOLVED else f"{lab.status}:{lab.reason}"
                counts[key] = counts.get(key, 0) + 1
                if lab.status == labels.RESOLVED and not u.unverified:
                    admissible += 1
                    first = first or d
                    last = d
        cfg = evaluate.Config(h=h)
        out["horizons"][str(h)] = {"label_counts": counts, "admissible_labels": admissible,
                                   "admissible_decision_days": [first.isoformat(), last.isoformat()] if first else None,
                                   "feature_history_needed": 251, "sessions_needed_first_fold": cfg.train_sessions + cfg.test_sessions + cfg.holdout_sessions,
                                   "folds_possible": len(evaluate.folds(sessions, cfg)),
                                   "admissible_for_promotion": 0,
                                   "why_not_promotion": "sessions are OBSERVED_PUBLICATION (no verified 2025 calendar); "
                                                        "no feature history (251 sessions); no fold fits"}
        if progress:
            progress(f"h={h}: {counts}")
    out["_universes"] = unis
    out["_sessions"] = sessions
    out["_stored"] = stored
    return out


def _count(xs) -> dict:
    c = {}
    for x in xs:
        c[x] = c.get(x, 0) + 1
    return c


# ---- corporate-action evidence -----------------------------------------------------------------------------

def classify_factor(f: float) -> str:
    for ratio, name in ((0.5, "1:1 bonus or 2:1 split"), (0.2, "5:1 split"), (0.1, "10:1 split"), (1 / 3, "2:1 bonus"),
                        (2 / 3, "1:2 bonus"), (0.25, "3:1 bonus or 4:1 split")):
        if abs(f - ratio) < 0.003:
            return f"SPLIT_OR_BONUS_LIKE ({name})"
    if f < 0.9:
        return "LARGE_DOWN_ADJUSTMENT (rights, demerger or capital action?)"
    if f < 1:
        return "SMALL_DOWN_ADJUSTMENT (dividend-like?)"
    return "UP_ADJUSTMENT (consolidation or data issue?)"


def corporate_actions(view: Panel, start: date, end: date) -> list[dict]:
    rows = view.db.execute("SELECT f.isin, f.day, f.factor, f.prior_close, f.prev_close, b.symbol, b.series FROM implied_factors f "
                           "JOIN bars b ON b.isin = f.isin AND b.day = f.day WHERE f.day BETWEEN ? AND ? ORDER BY f.day",
                           (start.isoformat(), end.isoformat())).fetchall()
    return [{"isin": r[0], "day": r[1], "factor": r[2], "prior_close": r[3], "exchange_base_price": r[4], "symbol": r[5],
             "series": r[6], "class": classify_factor(r[2])} for r in rows]


def base_price_on(view: Panel, isin: str, day: date) -> dict | None:
    """Exchange base price (PrvsClsgPric) on ``day`` against the previous stored close: the H-CA1 probe."""
    bars = view.bars(isin, day - timedelta(days=10), day)
    if len(bars) < 2 or bars[-1].day != day:
        return None
    prev, cur = bars[-2], bars[-1]
    return {"day": day.isoformat(), "previous_session": prev.day.isoformat(), "previous_close": prev.close,
            "exchange_base_price": cur.prev_close, "difference": round(cur.prev_close - prev.close, 4),
            "implied_factor": cur.prev_close / prev.close if prev.close else None}


# ---- ledger traces without a forecast ---------------------------------------------------------------------

def mechanical_trace(view: Panel, sessions: list[date], stored: set[date], isin: str, decision_day: date, q: int, h: int,
                     *, execution: ExecutionPolicy = ExecutionPolicy(), median_value: float, end: date | None = None,
                     index_name="Nifty 50", listed=None, capital: float = 10_000.0, actions=None) -> dict:
    """An intent of q shares frozen after ``decision_day``'s close, executed and reviewed by the ledger exactly as in
    replay; with no forecast at the expiry review the position exits (EXIT.v1: nothing justifies holding)."""
    k0 = sessions.index(decision_day)
    last = len(sessions) - 1 if end is None else max(i for i, d in enumerate(sessions) if d <= end)
    close = next(b.close for b in view.bars(isin, decision_day, decision_day))
    s = labels.slippage_for(median_value)
    limit = close * (1 + execution.max_entry_gap)
    led = Ledger(capital, execution)
    led.add_intent(Intent(f"{decision_day.isoformat()}:{isin}", isin, "", decision_day, q, close, limit, s, s,
                          reservation(q, limit, execution.charge_multiplier), k0 + execution.entry_delay_sessions,
                          {"forecast": "NONE: RECONSTRUCTED_NO_FORECAST"}))
    idx = view.index_levels(index_name)
    unchecked = view.unchecked_days()
    for k in range(k0 + 1, last + 1):
        day = sessions[k]
        have = day in stored
        bars = {i: b for i, b in view.cross_section(day)} if have else {}
        iopen = (idx.get(day) or (None, None))[0]
        f = view.implied_factors(isin, day, day).get(day)
        dv = view.discontinuities(isin, day, day).get(day)
        held = list(led.lots) or [isin]
        fs = {i: v for i in held if (v := view.implied_factors(i, day, day).get(day))}
        dd = {i: v[day] for i in held if (v := view.discontinuities(i, day, day)) and day in v}
        led.apply_actions(k, day, fs, day in unchecked, listed, dd or None, actions)
        led.execute_exits(k, day, have, bars, iopen)
        led.execute_entries(k, day, have, bars, h, iopen)
        led.mark(k, day, {i: b.close for i, b in bars.items()}, have)
        led.settle(k, day)
        for lot in led.lots.values():
            if not lot.exit_pending and k >= lot.review_index:
                lot.exit_pending, lot.exit_reason, lot.exit_decided_index = True, "EXPIRY_NO_FORECAST", k
                led.event("EXIT_DECIDED", day, isin=lot.isin, reason="EXPIRY_NO_FORECAST")
        if not led.lots and not led.intents and led.trades:
            break
    end_state = led.close_out(sessions[k])
    return {"label": "RECONSTRUCTED_NO_FORECAST", "isin": isin, "decision_day": decision_day.isoformat(), "q": q, "h": h,
            "decision_close": close, "limit": round(limit, 4), "slippage_per_side": s, "events": led.events,
            "trades": led.trades, "nav": led.nav, **end_state}


def size_at_cap(close: float, policy: allocate.Policy) -> int:
    """Whole shares at the per-stock cap from the decision close (no forecast, so no utility is optimised)."""
    return int(min(policy.cap_fraction * policy.W, policy.W * (1 - policy.reserve_fraction)) // close)
