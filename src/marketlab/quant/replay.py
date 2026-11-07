"""Causal replay: decisions after each close, executions at later opens, all money through the dated ledger.

Inputs per decision session are decision-time quantities only (``forecasts[day][isin]``: shrunk mean, scale,
quantiles, the decision close, the 20-session median traded value). Outcomes never enter: a label is not needed
to simulate, the ledger reads the panel's later bars as the market reveals them. The same function serves the
walk-forward folds and the stress runs (costs x2, slippage x2, entry one session late).

Per session k: (open) corporate actions on held lots -> pending exits -> pending entries; (close) marks and NAV;
(after the close, on decision sessions) settlement of proceeds -> EXIT.v1 reviews -> allocation of free slots and
cash -> new intents executing from session k + entry_delay.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

from . import allocate, labels
from .ledger import ExecutionPolicy, Intent, Ledger, reservation
from .linalg import shrunk_correlation

RULE_TRIGGERS = ("UNDER_SURVEILLANCE", "SUSPENDED", "PERIODIC_CALL_AUCTION", "SURVEILLANCE_UNKNOWN")
FALLBACK_RHO = 0.3  # spec 0 assumption, used only when fewer than 20 common return days exist


def _corr(view, isins: list[str], sessions: list[date], k: int) -> list[list[float]]:
    if len(isins) == 1:
        return [[1.0]]
    lo = sessions[max(0, k - 60)]
    series = {}
    for isin in isins:
        series[isin] = {b.day: math.log(b.close / b.prev_close) for b in view.bars(isin, lo, sessions[k])
                        if b.close > 0 and b.prev_close > 0}
    common = sorted(set.intersection(*(set(s) for s in series.values())))
    if len(common) < 20:
        return [[1.0 if i == j else FALLBACK_RHO for j in range(len(isins))] for i in range(len(isins))]
    return shrunk_correlation([[series[i][d] for d in common] for i in isins], 0.5)


def candidate_for(isin: str, fc: dict, execution: ExecutionPolicy) -> allocate.Candidate:
    """Decision-time candidate: price = the decision close; cash blocked at the limit L (the most an effective fill
    price may be); the base slippage tier both ways (stress multipliers act only on execution)."""
    s = labels.slippage_for(fc["median_value"])
    limit = fc["ref_close"] * (1 + execution.max_entry_gap)
    return allocate.Candidate(isin, fc["ref_close"], fc["mu_shrunk"], fc["sigma_hat"], 2 * s, downside_q10(fc),
                              fc.get("symbol", ""), cash_price=limit)


def downside_q10(fc: dict) -> float:
    """The bad-month (10%) outcome of the stock's OWN return, for gates and exits about money lost (E22); the
    excess-return q10 only when a model predates absolute calibration."""
    v = fc.get("q10_abs")
    if v is None:
        v = fc.get("q10")
    return float("nan") if v is None else v


def plan_entries(led: Ledger, view, sessions: list[date], k: int, day: date, todays: dict, policy: allocate.Policy,
                 execution: ExecutionPolicy) -> dict:
    """Allocate free slots and settled cash among today's forecasts; freeze the chosen quantities as intents."""
    slots = policy.K - sum(1 for lot in led.lots.values() if not lot.exit_pending) - len(led.intents)
    busy = set(led.lots) | {i.isin for i in led.intents.values()}
    if slots <= 0:
        return {"note": "NO_FREE_SLOT"}
    cands, rejected = [], {}
    for isin, fc in todays.items():
        if isin in busy or "abstain" in fc or not (fc.get("ref_close", 0) > 0):
            continue
        c = candidate_for(isin, fc, execution)
        ok, why = allocate.entry_gate(c, policy)
        if ok and not allocate.qualifies(c, policy, policy.W * (1 - policy.reserve_fraction)):
            ok, why = False, ["FAILS_GATES_AT_QUANTITY"]  # same pool rule as the ranking
        if ok:
            cands.append(c)
        else:
            for w in why:
                rejected[w] = rejected.get(w, 0) + 1
    if not cands:
        return {"rejected": rejected, "note": "NO_CANDIDATE_PASSES_GATE"}
    cands.sort(key=lambda c: -(c.mu - allocate.VARIABLE_ROUND_TRIP - c.slippage))
    cands = cands[:10]
    corr = _corr(view, [c.isin for c in cands], sessions, k)
    reserve = policy.reserve_fraction * policy.W
    out = allocate.plan(cands, corr, replace(policy, K=slots), max(0.0, led.available_cash(reserve)))
    for v in out["rejected"].values():
        for w in v:
            rejected[w] = rejected.get(w, 0) + 1
    for isin, q in out["quantities"].items():
        fc, c = todays[isin], next(x for x in cands if x.isin == isin)
        s = c.slippage / 2
        pos = out["positions"][isin]
        p_above = fc.get("_p_above")
        record = {k_: fc[k_] for k_ in ("mu_hat", "se", "mu_shrunk", "sigma_hat", "q10", "q50", "q90", "p_positive")
                  if k_ in fc}
        record |= {"costs_at_q": {k_: pos[k_] for k_ in ("value", "charges", "slippage", "cost_fraction", "net_edge")},
                   "p_active_beats_costs_at_q": p_above(pos["cost_fraction"]) if p_above else None,
                   "p_note": "P(gross excess return > round-trip costs at this quantity); assumes a zero benchmark "
                             "return, so it is the probability of net profit only in a flat market"}
        limit = fc["ref_close"] * (1 + execution.max_entry_gap)
        led.add_intent(Intent(f"{day.isoformat()}:{isin}", isin, fc.get("symbol", ""), day, q, fc["ref_close"], limit, s, s,
                              reservation(q, limit, execution.charge_multiplier), k + execution.entry_delay_sessions, record))
    return {"rejected": rejected, "planned": out["quantities"], "method": out["method"]}


def review_exits(led: Ledger, k: int, day: date, todays: dict, exclusions: dict, policy: allocate.Policy, h: int,
                 execution: ExecutionPolicy):
    """EXIT.v1 for every held lot: triggers before expiry, a re-forecast at expiry, hysteresis; no forecast for a
    lot that must be reviewed means EXIT (nothing justifies holding it)."""
    alts = [candidate_for(i, fc, execution) for i, fc in todays.items()
            if i not in led.lots and "abstain" not in fc and fc.get("ref_close", 0) > 0]
    for isin, lot in led.lots.items():
        if lot.exit_pending:
            continue
        triggers = []
        reason = exclusions.get(isin)
        if reason and (reason in RULE_TRIGGERS or reason.startswith("SERIES_") or reason.startswith("BAND_")):
            triggers.append("RULE_" + reason)
        realized = (lot.units * lot.last_close) / (lot.q * lot.entry_open) - 1
        q10 = downside_q10(lot.forecast)  # E22: the lot's own (absolute) return against its absolute log q10
        if not math.isnan(q10) and realized > -1 and math.log1p(realized) < q10:
            triggers.append("BELOW_ENTRY_Q10")
        expired = k >= lot.review_index
        if not expired and not triggers:
            continue
        fc = todays.get(isin)
        if fc is None or "abstain" in fc:
            lot.exit_pending, lot.exit_reason, lot.exit_decided_index = True, "NO_CONTINUATION_FORECAST", k
            led.event("EXIT_DECIDED", day, isin=isin, reason="NO_CONTINUATION_FORECAST", triggers=triggers)
            continue
        pos = allocate.Position(isin, lot.units * lot.last_close, fc["mu_shrunk"], fc["sigma_hat"], q10 if q10 is not None else float("nan"),
                                realized, k - lot.entry_index + 1, h)
        d = allocate.exit_decision(pos, alts, policy, flags=tuple(t for t in triggers if t != "BELOW_ENTRY_Q10"))
        if d["action"] == "HOLD":
            if expired:
                lot.review_index = k + h  # a new horizon is a new decision with its own forecast (spec 5.5 rule 3)
            lot.holds.append({"day": day.isoformat(), "u_hold": d.get("u_hold"), "u_alt": d.get("u_alt"),
                              "mu_shrunk": fc["mu_shrunk"], "triggers": d.get("triggers", [])})
            led.event("HOLD", day, isin=isin, reason=d.get("reason"), u_hold=d.get("u_hold"), u_alt=d.get("u_alt"))
        else:
            lot.exit_pending, lot.exit_reason, lot.exit_decided_index = True, d.get("reason"), k
            led.event("EXIT_DECIDED", day, isin=isin, reason=d.get("reason"), u_hold=d.get("u_hold"), u_alt=d.get("u_alt"),
                      triggers=d.get("triggers", []))


def simulate(view, sessions: list[date], panel_days: set[date], start_k: int, end_k: int, forecasts: dict, *,
             policy: allocate.Policy, execution: ExecutionPolicy = ExecutionPolicy(), h: int = 20,
             index_name: str = "Nifty 50", exclusions: dict | None = None, listed=None, actions=None) -> dict:
    """Run sessions start_k..end_k. ``forecasts``: {day: {isin: decision-time forecast}} for decision sessions.
    Returns the ledger's trades, events, NAV series and the end-of-period valuation."""
    led = Ledger(policy.W, execution)
    idx = view.index_levels(index_name, sessions[start_k], sessions[end_k])
    unchecked = view.unchecked_days(sessions[start_k], sessions[end_k])
    exclusions = exclusions or {}
    plans = {}
    for k in range(start_k, end_k + 1):
        day = sessions[k]
        have = day in panel_days
        bars = {isin: b for isin, b in view.cross_section(day)} if have else {}
        iopen = (idx.get(day) or (None, None))[0]
        held = list(led.lots)
        factors = {}
        for isin in held:
            f = view.implied_factors(isin, day, day).get(day)
            if f is not None:
                factors[isin] = f
        disc = {i: v[day] for i in held if (v := view.discontinuities(i, day, day)) and day in v}
        led.apply_actions(k, day, factors, day in unchecked, listed, disc, actions)
        led.execute_exits(k, day, have, bars, iopen)
        led.execute_entries(k, day, have, bars, h, iopen)
        led.mark(k, day, {i: b.close for i, b in bars.items()}, have)
        led.settle(k, day)
        if day in forecasts and have:
            todays = forecasts[day]
            review_exits(led, k, day, todays, exclusions.get(day, {}), policy, h, execution)
            plans[day.isoformat()] = plan_entries(led, view, sessions, k, day, todays, policy, execution)
    end = led.close_out(sessions[end_k])
    navs = [r["nav"] for r in led.nav]
    rejected = {}
    for p in plans.values():
        for w, n in (p.get("rejected") or {}).items():
            rejected[w] = rejected.get(w, 0) + n
    return {"trades": led.trades, "events": led.events, "event_counts": led.counts, "nav": led.nav, **end,
            "n_trades": len(led.trades), "max_drawdown": _max_dd(navs),
            "time_in_cash": (sum(1 for r in led.nav if r["n_positions"] == 0) / len(led.nav)) if led.nav else float("nan"),
            "rejected": rejected, "execution": execution.to_json(), "policy": policy.to_json()}


def _max_dd(curve: list[float]) -> float:
    peak, dd = -float("inf"), 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd
