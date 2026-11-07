"""Today's research ranking (RANK.v1): every stock of the latest session classified, with the reasons and the numbers
behind each call. Research output only: nothing here can reach a broker, and until a model passes the frozen
promotion rule (spec 8.6) every call is UNVALIDATED.

Pipeline (the same code as the paper decision: ``evaluate.build_dataset`` then ``decide.fit_today``):

1. Universe screen U_D (spec 3.1) on the latest stored session D: structural exclusions (series, ETF, liquidity, price
   per share against the per-stock cap) make a stock INELIGIBLE; exchange risk flags (surveillance, suspension,
   periodic call auction, unknown surveillance status) make it AVOID.
2. Feature set A for the remaining stocks (momentum, reversal, volatility, liquidity, 250-session range, gap; market
   backdrop), each stock's features ranked against the day's cross-section. Missing history or an unexplained price
   jump in a window: NO_FORECAST.
3. Ridge regression (trained on every resolved 20-session label available, purged and calibrated) gives the mean
   gross excess return over the Nifty 50 for the next h sessions; a 50-refit block bootstrap gives its standard error
   and empirical-Bayes shrinkage toward zero; split-conformal residuals give the 10/50/90% outcome range.
4. Exact round-trip costs at the whole-share quantity the per-stock cap allows (brokerage, STT, stamp duty, exchange
   and SEBI fees, GST, the DP charge, slippage both ways). Gates at that quantity: shrunk mean - costs >= minimum
   edge, and 10% outcome - costs >= -tail limit.
5. Classes, in this order:
     BUY_CANDIDATE  passes both gates and the allocator (K positions, cap, cash reserve, correlation) chose it;
     QUALIFIES      passes both gates but the allocator preferred other stocks;
     AVOID          the shrunk forecast is at or below -(costs + minimum edge): the model's negative view is as strong
                    as a buy would need to be positive (or the exchange flags the stock, step 1);
     HIGH_RISK      the 10% outcome after costs is worse than -tail limit: a bad month (1 in 10) would lose more than
                    the policy accepts, whatever the expected edge;
     HOLD_OFF       everything between: the expected edge does not cover the costs either way.
6. The ranking is written once to runs/rankings/<day>/<digest>.json. A ranking created before the entry session
   opens is forward evidence: its outcomes, scored later (``forward_record``), cannot have been seen.

All arithmetic is here (deterministic); explanations (marketlab.explain) only format these numbers.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date, datetime
from pathlib import Path

from .. import decisions
from ..common import IST, now
from . import allocate, candidates, decide, evaluate, features, forecast, labels, registry, replay
from .ledger import reservation
from .sessions import next_session

VERSION = "RANK.v1"
FOLDER = "rankings"
CLASSES = ("BUY_CANDIDATE", "QUALIFIES", "HOLD_OFF", "HIGH_RISK", "AVOID", "INELIGIBLE", "NO_FORECAST")
LOW_LIQUIDITY_VALUE = 5 * 10_000_000  # the old screen floor: below it the stock is analysed and flagged (E21)
RISK_EXCLUSIONS = ("UNDER_SURVEILLANCE", "SUSPENDED", "PERIODIC_CALL_AUCTION", "SURVEILLANCE_UNKNOWN")


def edge_order(card: dict) -> float:
    """Sort key: best net edge first; a card without one last. (`net_edge or -9` sent an edge of exactly 0.0 to
    the bottom, because 0.0 is falsy: audit finding 2026-11-07.)"""
    v = (card.get("gates") or {}).get("net_edge")
    return -v if v is not None else float("inf")


def _f(x, nd=6):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


def _risk_reason(reason: str) -> bool:
    if reason in RISK_EXCLUSIONS:
        return True
    if reason.startswith("BAND_"):
        return True  # a price band below 10% is the exchange's own risk measure
    return False


def eligibility_checks(view, day: date, isin: str, bar, sp, rule_inputs: dict | None, window_stats: dict, names: dict) -> list[dict]:
    """The universe rules applied to one stock, with the values compared (spec 3.1). ``window_stats`` gives the
    sessions traded and the median traded value over the screen's lookback."""
    from .panel import is_etf_name
    ri = rule_inputs or {}
    series = ri.get("series", {}).get(bar.symbol, bar.series)
    traded, med = window_stats.get(isin, (0, None))
    reg = ri.get("reg", {}).get(bar.symbol)
    band = ri.get("band", {}).get(bar.symbol, "absent") if ri.get("have_band") else "unknown"
    allowed = tuple(getattr(sp, "series", ("EQ",)))
    checks = [
        {"rule": "SERIES", "value": series, "need": " or ".join(allowed), "pass": series in allowed},
        {"rule": "NOT_AN_ETF", "value": names.get(isin), "need": "an operating company's share", "pass": not is_etf_name(isin, names.get(isin))},
        {"rule": "TRADED_EVERY_SESSION", "value": traded, "need": sp.lookback, "pass": traded >= sp.lookback},
    ]
    if sp.v_min > 0:  # E21: no liquidity floor by default; illiquidity is costed and flagged instead
        checks.append({"rule": "MEDIAN_VALUE_20", "value": _f(med, 0), "need": sp.v_min, "pass": med is not None and med >= sp.v_min})
    if sp.price_max_fraction is not None:  # E21: no price rule by default; affordability is decided when buying
        checks.append({"rule": "PRICE_FITS_HALF_POSITION", "value": bar.close, "need": sp.price_max_fraction * sp.W,
                       "pass": bar.close <= sp.price_max_fraction * sp.W})
    if not ri.get("have_reg"):
        checks.append({"rule": "SURVEILLANCE", "value": "unknown (file not admissible)", "need": "not under ASM/GSM", "pass": None})
    elif reg is None:
        checks.append({"rule": "SURVEILLANCE", "value": "not listed in the regulatory indicators", "need": "not under ASM/GSM", "pass": True})
    else:
        flag = reg.get("surveillance")
        checks.append({"rule": "SURVEILLANCE", "value": "suspended" if reg.get("suspended") else
                       "call auction" if reg.get("call_auction") else "unknown" if flag is None else ("flagged" if flag else "clear"),
                       "need": "not under ASM/GSM", "pass": None if flag is None and not reg.get("suspended") else
                       (not reg.get("suspended") and not reg.get("call_auction") and not flag)})
    if band == "unknown":
        checks.append({"rule": "PRICE_BAND", "value": "unknown (file not admissible)", "need": f">= {sp.min_band_pct:g}%", "pass": None})
    elif band == "absent" or band is None:
        checks.append({"rule": "PRICE_BAND", "value": "no band (F&O stock)" if band is None else "not listed",
                       "need": f">= {sp.min_band_pct:g}%", "pass": True})
    else:
        checks.append({"rule": "PRICE_BAND", "value": band, "need": f">= {sp.min_band_pct:g}%", "pass": band >= sp.min_band_pct})
    return checks


def _window_stats(view, sessions: list[date], day: date, lookback: int) -> dict:
    i = sessions.index(day)
    counts, values = {}, {}
    for d in sessions[max(0, i - lookback + 1):i + 1]:
        for isin, b in view.cross_section(d):
            counts[isin] = counts.get(isin, 0) + (1 if b.volume > 0 else 0)
            values.setdefault(isin, []).append(b.value)
    out = {}
    for isin, vs in values.items():
        s = sorted(vs)
        out[isin] = (counts.get(isin, 0), statistics.median(s))  # an even count averages the middle pair
    return out


def _contributions(model: forecast.Model, x: dict) -> dict:
    beta = model.beta
    items = [{"feature": f, "beta": _f(beta[j + 1], 8), "x": _f(x.get(f), 6), "contribution": _f(beta[j + 1] * x[f], 8),
              "group": "stock" if f in features.STOCK_FEATURES else "market"} for j, f in enumerate(features.FEATURES)]
    stock = sum(i["contribution"] for i in items if i["group"] == "stock")
    market = sum(i["contribution"] for i in items if i["group"] == "market")
    return {"intercept": _f(beta[0], 8), "items": items, "stock_total": _f(stock, 8), "market_total": _f(market, 8),
            "common_total": _f(beta[0] + market, 8)}


def _flip(card: dict, policy: allocate.Policy, model: forecast.Model) -> dict:
    """What would change the call: margins to each gate in forecast units, and the single stock feature that could
    move the forecast most (from its current rank to the most favourable rank, other inputs unchanged)."""
    fc, costs = card["forecast"], card["costs"]
    thr = costs["cost_fraction"] + policy.min_edge
    q10 = replay.downside_q10(fc)  # E22: the stock's own bad month, not its month against the Nifty
    v = costs.get("value") or 0.0
    have = not math.isnan(q10) and v > 0
    out = {"edge_threshold": _f(thr), "edge_margin": _f(fc["mu_shrunk"] - thr),
           "tail_margin": _f(allocate.capital_tail_loss(q10, costs["cost_fraction"], v, policy) + policy.tail_limit)
           if have else None,
           # the lowest bad-month return of the stock itself that the tail gate accepts at this position size:
           # (v / W) * (q10_abs - cost) >= -L  <=>  q10_abs >= cost - L * W / v
           "tail_q10_threshold": _f(costs["cost_fraction"] - policy.tail_limit * policy.W / v) if v > 0 else None,
           "tail_q10_basis": "ABSOLUTE" if fc.get("q10_abs") is not None else "EXCESS",
           "avoid_threshold": _f(-thr), "avoid_margin": _f(-thr - fc["mu_shrunk"])}
    shrink = fc.get("shrink_specific") if fc.get("shrink_specific") is not None else (fc.get("shrink_factor") or 0.0)
    best = None
    for it in card["contributions"]["items"]:
        if it["group"] != "stock" or it["beta"] is None or it["x"] is None:
            continue
        target = 0.5 if it["beta"] > 0 else -0.5
        gain = it["beta"] * (target - it["x"])  # in mu_hat units
        if best is None or gain > best["max_gain_mu_hat"]:
            best = {"feature": it["feature"], "max_gain_mu_hat": _f(gain, 8), "max_gain_shrunk": _f(gain * shrink, 8),
                    "to_rank": target}
    out["best_single_lever"] = best
    if fc["mu_shrunk"] < thr:
        need = thr - fc["mu_shrunk"]
        out["needed_rise_shrunk"] = _f(need)
        out["needed_rise_mu_hat"] = _f(need / shrink) if shrink > 0 else None
        out["one_feature_could_clear"] = bool(best and best["max_gain_shrunk"] is not None and best["max_gain_shrunk"] >= need)
    return out


def _bigger_account(c: allocate.Candidate, policy: allocate.Policy) -> list[dict]:
    """Round-trip cost fraction of the same stock at larger account tiers (spec 5.4 caps): the fixed DP charge and
    rupee rounding weigh less as positions grow. Shows how much of a HOLD_OFF is the account size."""
    out = []
    for W in (policy.W, 50_000.0, 200_000.0):
        tier = allocate.Policy.for_capital(W)
        cap = min(tier.cap_fraction * W, W * (1 - tier.reserve_fraction))
        q = int(cap // c.price) if c.price > 0 else 0
        if q > 0:
            pc = allocate.position_costs(c, q)
            out.append({"capital": W, "position": round(q * c.price, 2), "q": q, "cost_fraction": _f(pc["cost_fraction"])})
    return out


def cost_and_gates(c: allocate.Candidate, cap: float, policy: allocate.Policy) -> tuple[int, dict, dict, dict]:
    """Whole shares under the per-stock cap, exact round-trip costs and both gates at that quantity. When not even one
    share fits (E21: such stocks are analysed, not screened out), costs and gates are computed at ONE share for
    reference and ``NO_WHOLE_SHARE_FITS`` leads the gate reasons, so every downstream number stays defined.
    Returns (q, position costs, the card's costs block, the card's gates block)."""
    q = int(cap // c.price) if c.price > 0 else 0
    q_costed = q if q > 0 else (1 if c.price > 0 else 0)
    if q_costed == 0:
        pc = {"value": 0.0, "charges": 0.0, "slippage": 0.0, "cost_fraction": float("inf")}
        reasons_q, gate = ["NO_WHOLE_SHARE_FITS"], {}
    else:
        pc = allocate.position_costs(c, q_costed)
        reasons_q, gate = allocate.position_gate(c, q_costed, policy)
        if q == 0:
            reasons_q = ["NO_WHOLE_SHARE_FITS"] + reasons_q
    costs = {"q": q, "q_costed": q_costed, "value": pc.get("value"), "buy_charges": pc.get("buy_charges"),
             "sell_charges_incl_dp": pc.get("sell_charges_incl_dp"), "charges": _f(pc.get("charges"), 2),
             "slippage_rupees": _f(pc.get("slippage"), 2), "slippage_fraction": _f(c.slippage),
             "charge_fraction": _f(pc.get("charge_fraction")), "cost_fraction": _f(pc.get("cost_fraction")),
             "limit_price": round(c.blocked_price(), 2),
             "cash_blocked": str(reservation(q, c.blocked_price())) if q > 0 else "0",
             "dp_charge": allocate.FIXED_SELL, "bigger_accounts": _bigger_account(c, policy)}
    gates = {"at_quantity": reasons_q, "at_cap": allocate.entry_gate(c, policy)[1],
             "net_edge": _f(gate.get("net_edge")), "threshold": _f(gate.get("threshold"))}
    return q, pc, costs, gates


def classify(card: dict, policy: allocate.Policy) -> tuple[str, list[str]]:
    gates = card["gates"]["at_quantity"]
    fc, costs = card["forecast"], card["costs"]
    if card["allocation"]["selected"]:
        return "BUY_CANDIDATE", ["PASSES_GATES_AND_ALLOCATOR"]
    if not gates:
        return "QUALIFIES", [card["allocation"].get("why_not") or "NOT_SELECTED"]
    tail = "TAIL_LIMIT_AT_QUANTITY" in gates
    thr = (costs.get("cost_fraction") if costs.get("cost_fraction") is not None else 0.0) + policy.min_edge
    if fc["mu_shrunk"] <= -thr:  # the model's own negative view outranks affordability
        return "AVOID", ["MODEL_EXPECTS_UNDERPERFORMANCE"] + (["DOWNSIDE_TAIL_BEYOND_LIMIT"] if tail else [])
    if "NO_WHOLE_SHARE_FITS" in gates:  # analysed, but one share costs more than the per-stock cap at this capital
        return "HOLD_OFF", ["ONE_SHARE_ABOVE_POSITION_CAP"] + (["LEANS_NEGATIVE"] if fc["mu_shrunk"] < 0 else ["LEANS_POSITIVE"])
    if tail:
        return "HIGH_RISK", ["DOWNSIDE_TAIL_BEYOND_LIMIT"] + (["EDGE_BELOW_COST"] if "EDGE_BELOW_COST_AT_QUANTITY" in gates else [])
    return "HOLD_OFF", ["EDGE_BELOW_COST"] + (["LEANS_NEGATIVE"] if fc["mu_shrunk"] < 0 else ["LEANS_POSITIVE"])


def policy_for_capital(saved: dict, capital: float, *, min_edge: float | None = None,
                       tail_limit: float | None = None) -> allocate.Policy:
    """The same owner policy at a different capital. Fractions and K come from the spec 5.4 tier for the new
    capital unless the stored policy already departed from its own tier (an explicit owner override, which is
    kept); gamma follows 2/W; min_edge and tail_limit are spec-fixed and never scale."""
    w0 = float(saved.get("W") or capital)
    old_tier, tier = allocate.Policy.for_capital(w0), allocate.Policy.for_capital(float(capital))
    k = int(saved["K"]) if saved.get("K") not in (None, old_tier.K) else tier.K
    capf = float(saved["cap_fraction"]) if saved.get("cap_fraction") not in (None, old_tier.cap_fraction) else tier.cap_fraction
    g0 = float(saved.get("gamma") or (2.0 / w0))
    m = (2.0 / w0) / g0 if g0 > 0 else 1.0  # the owner's risk multiplier, recovered from gamma = 2/(mW)
    return allocate.Policy(float(capital), reserve_fraction=float(saved.get("reserve_fraction", 0.20)),
                           cap_fraction=capf, K=k, gamma=2.0 / (m * float(capital)),
                           min_edge=float(min_edge if min_edge is not None else saved.get("min_edge", 0.001)),
                           tail_limit=float(tail_limit if tail_limit is not None else saved.get("tail_limit", 0.08)))


RESTATE_BASIS = "RESTATED_GREEDY_NO_CORRELATION"


def restate(body: dict, capital: float, *, min_edge: float | None = None, tail_limit: float | None = None) -> dict:
    """The same day's ranking read at a different capital, from the stored forecasts alone: no refit happens,
    because capital changes only the whole-share quantity, the exact charges, the gates and the allocation.

    Honest limits, recorded in the returned body under "restated":
      - a stock the stored screen excluded on price has no forecast in the artifact, so a larger capital can only
        mark it NEWLY_ELIGIBLE_NEEDS_RANK_RUN, never rank it;
      - selection uses a greedy top-K by net edge, not the correlation-aware allocator, so BUY_CANDIDATE here means
        "clears both gates and fits the cap/cash/K", pending a real `rank --capital` run;
      - P(beats costs) needs the calibration residuals, which the artifact does not carry, so it is dropped.
    This body is never written as an artifact: it has no digest and no path."""
    if body.get("status") != "RANKED" or not body.get("stocks"):
        return dict(body, restated={"capital": float(capital), "basis": "NOT_RANKED", "changed": 0})
    policy = policy_for_capital(body.get("policy") or {}, capital, min_edge=min_edge, tail_limit=tail_limit)
    cap = min(policy.cap_fraction * policy.W, policy.W * (1 - policy.reserve_fraction))
    old_rule = (body.get("screen_policy") or {}).get("price_max")  # artifacts before E21 screened on price
    price_max = policy.W * 0.5 if old_rule is not None else float("inf")
    out, priced_out, newly = [], 0, 0
    for src in body["stocks"]:
        card = dict(src)
        close = card.get("close") or 0.0
        if "forecast" not in card:
            if card.get("reasons") == ["PRICE_ABOVE_HALF_POSITION"] and 0 < close <= price_max:
                card["class"], card["reasons"] = "NO_FORECAST", ["NEWLY_ELIGIBLE_NEEDS_RANK_RUN"]
                newly += 1
            out.append(card)
            continue
        if close > price_max:
            card["class"], card["reasons"] = "INELIGIBLE", ["PRICE_ABOVE_HALF_POSITION"]
            for k in ("gates", "allocation", "flip", "rank", "rank_of"):
                card.pop(k, None)
            priced_out += 1
            out.append(card)
            continue
        fc = card["forecast"]
        c = allocate.Candidate(card["isin"], close, fc["mu_shrunk"], fc["sigma_hat"],
                               card["costs"].get("slippage_fraction") or 0.002,
                               replay.downside_q10(fc), card.get("symbol") or "",
                               cash_price=card["costs"].get("limit_price") or 0.0)
        q, pc, card["costs"], card["gates"] = cost_and_gates(c, cap, policy)
        card["p_beats_costs"] = None
        card["allocation"] = {"selected": False, "q": None, "value": None, "costs_at_plan_q": None}
        card["_c"] = c
        out.append(card)
    # Greedy selection: best net edge first, whole shares, within the per-stock cap, the cash after the reserve and K.
    eligible = sorted((c for c in out if c.get("gates") and not c["gates"]["at_quantity"]),
                      key=edge_order)
    free = policy.W * (1 - policy.reserve_fraction)
    for card in eligible:
        if sum(1 for s in out if (s.get("allocation") or {}).get("selected")) >= policy.K:
            card["allocation"]["why_not"] = "NOT_SELECTED_K_LIMIT"
            continue
        c, q = card.pop("_c"), card["costs"]["q"]
        blocked = float(reservation(q, c.blocked_price())) if q > 0 else 0.0
        if q > 0 and blocked <= free:
            free -= blocked
            card["allocation"] = {"selected": True, "q": q, "value": card["costs"]["value"],
                                  "costs_at_plan_q": {"cost_fraction": card["costs"]["cost_fraction"],
                                                      "net_edge": card["gates"]["net_edge"]}}
        else:
            card["allocation"]["why_not"] = "CASH_AFTER_RESERVE_EXHAUSTED"
    for card in out:
        card.pop("_c", None)
        if card.get("gates"):
            card["class"], card["reasons"] = classify(card, policy)
            card["flip"] = _flip(card, policy, None)
    ranked = sorted([s for s in out if "gates" in s], key=edge_order)
    for s in out:
        s.pop("rank", None), s.pop("rank_of", None)
    for i, s in enumerate(ranked, 1):
        s["rank"], s["rank_of"] = i, len(ranked)
    new = dict(body)
    new.pop("digest", None), new.pop("artifact", None)
    new["stocks"] = out
    new["counts"] = {k: sum(1 for s in out if s["class"] == k) for k in CLASSES}
    new["policy"] = policy.to_json()
    new["policy_digest"] = policy.digest()
    new["screen_policy"] = dict(body.get("screen_policy") or {}, price_max=price_max if old_rule is not None else None)
    new["restated"] = {"capital": float(policy.W), "from_capital": float((body.get("policy") or {}).get("W") or 0),
                       "from_digest": body.get("digest"), "from_day": body.get("day"), "basis": RESTATE_BASIS,
                       "priced_out": priced_out, "newly_eligible_needs_run": newly,
                       "min_edge": policy.min_edge, "tail_limit": policy.tail_limit,
                       "from_min_edge": (body.get("policy") or {}).get("min_edge"),
                       "from_tail_limit": (body.get("policy") or {}).get("tail_limit"),
                       "note": "Costs, gates and classes recomputed at this capital from the stored forecasts; "
                               "the model was not refitted. Selection is greedy by net edge, not the "
                               "correlation-aware allocator, and P(beats costs) is unavailable here."}
    return new


def _digest(body: dict) -> str:
    raw = json.dumps({k: v for k, v in body.items() if k not in ("created_at", "artifact", "digest", "forward")},
                     sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build(panel, cfg: evaluate.Config, *, root: Path, calendar, rule_inputs_fn=None, actions=None, bootstrap: int = 50,
          progress=None, write: bool = True, created_at: datetime | None = None, extra: dict | None = None) -> dict:
    """The ranking for the latest stored session. Returns the artifact body (also written once unless write=False)."""
    created = created_at or now()
    policy = cfg.effective_policy()
    runs = decisions.runs_dir(root)
    spec = candidates.require(cfg.candidate, cfg.h, cfg.ablate)
    view = panel.view(None)
    stored = view.sessions()
    if not stored:
        return {"version": VERSION, "status": "NO_PANEL", "stocks": []}
    ds = evaluate.build_dataset(view, cfg, calendar=calendar, rule_inputs_fn=rule_inputs_fn, actions=actions, progress=progress)
    day = max(ds.panel_days)
    u = ds.universe.get(day)
    entry = next_session(calendar, day, ds.sessions)
    ri = rule_inputs_fn(entry) if (rule_inputs_fn and entry) else None
    bars = dict(view.cross_section(day))
    names = view.names_on(day)
    sp = cfg.screen
    wstats = _window_stats(view, ds.sessions, day, sp.lookback) if day in ds.sessions else {}
    promo, problems = registry.verified_promotion(runs, cfg.candidate, cfg.h, policy.digest())
    body = {"version": VERSION, "day": day.isoformat(), "entry_session": entry.isoformat() if entry else None,
            "candidate": cfg.candidate, "h": cfg.h, "candidate_spec": candidates.describe(spec, cfg.ablate),
            "policy": policy.to_json(), "policy_digest": policy.digest(), "execution": cfg.execution_json(),
            "screen_policy": {"v_min": sp.v_min, "lookback": sp.lookback, "price_max": sp.price_max_fraction * sp.W if sp.price_max_fraction is not None else None,
                              "min_band_pct": sp.min_band_pct, "series": list(sp.series)},
            "validation": _validation(ds, cfg, runs, promo, problems),
            "data": {"panel_first": min(stored).isoformat(), "panel_last": max(stored).isoformat(),
                     "sessions": len(ds.sessions), "stored_sessions": len(ds.panel_days),
                     "missing_sessions": [d.isoformat() for d in ds.missing_sessions][-20:],
                     "missing_sessions_count": len(ds.missing_sessions),
                     "session_basis": {str(k): v for k, v in ds.session_basis.items()},
                     "content_hash": ds.manifest_hash, "label_counts": ds.label_counts,
                     "rule_inputs": {"availability": (ri or {}).get("availability", "NONE"),
                                     "have_surveillance_file": bool((ri or {}).get("have_reg")),
                                     "have_band_file": bool((ri or {}).get("have_band")),
                                     "evidence": (ri or {}).get("evidence", {})},
                     "actions": actions.summary() if actions is not None else None},
            "universe": {"kept": len(u.isins) if u else 0, "excluded": u.stats if u else {},
                         "unverified": u.unverified if u else ["DAY_NOT_A_SESSION"]},
            **(extra or {})}
    fit = decide.fit_today(ds, cfg, day, bootstrap=bootstrap) if u and u.isins else {"error": "EMPTY_UNIVERSE", "rows": 0}
    model = fit.get("model")
    stocks = []
    if model is None:
        body["status"] = fit["error"]
    elif model.calibration_n < forecast.MIN_CALIBRATION:
        body["status"] = "INSUFFICIENT_CALIBRATION"
    else:
        body["status"] = "RANKED"
    rows_today = {o["isin"]: o for o in fit.get("today", [])}
    all_today = {o["isin"]: o for o in fit.get("today_all", [])} if model else {o["isin"]: o for o in ds.opportunities if o["day"] == day}
    todays = fit.get("todays", {}) if body["status"] == "RANKED" else {}
    cands = {i: replay.candidate_for(i, fc, cfg.execution) for i, fc in todays.items()}
    passing = [c for c in cands.values() if allocate.entry_gate(c, policy)[0]]
    plan = {"quantities": {}, "positions": {}}
    if passing:
        passing.sort(key=lambda c: -(c.mu - allocate.VARIABLE_ROUND_TRIP - c.slippage))
        pool = passing[:10]
        corr = replay._corr(view, [c.isin for c in pool], ds.sessions, len(ds.sessions) - 1)
        plan = allocate.plan(pool, corr, policy, policy.W * (1 - policy.reserve_fraction))
    selected = plan.get("quantities", {})
    cap = min(policy.cap_fraction * policy.W, policy.W * (1 - policy.reserve_fraction))
    for isin, b in sorted(bars.items(), key=lambda kv: kv[1].symbol):
        card = {"isin": isin, "symbol": b.symbol, "name": names.get(isin), "series": b.series, "close": b.close,
                "prev_close": b.prev_close, "day_change": _f(b.close / b.prev_close - 1) if b.prev_close else None,
                "value_today": _f(b.value, 0), "median_value_20": _f((wstats.get(isin) or (0, None))[1], 0)}
        excluded = (u.excluded.get(isin) if u else "DAY_NOT_A_SESSION") if (not u or isin not in u.isins) else None
        card["checks"] = eligibility_checks(view, day, isin, b, sp, ri, wstats, names)
        if excluded:
            card["class"] = "AVOID" if _risk_reason(excluded) else "INELIGIBLE"
            card["reasons"] = [excluded]
            stocks.append(card)
            continue
        o = rows_today.get(isin) or all_today.get(isin)
        raw = (o or {}).get("features", {})
        card["features"] = {f: _f(raw.get(f), 8) for f in features.FEATURES}
        if actions is not None:
            chain = ds.lineage.get(isin, [isin])
            start = ds.sessions[max(0, len(ds.sessions) - features.MIN_HISTORY)]
            card["actions"] = [la.to_json() for la in actions.for_isins(chain, start=start, end=day)
                               if la.price_factor or la.dividend_cash or set(la.kinds) & {"DEMERGER", "RIGHTS", "SCHEME"}]
            if len(chain) > 1:
                card["lineage"] = chain
        fc = todays.get(isin)
        if fc is None:
            card["class"] = "NO_FORECAST"
            miss = (o or {}).get("missing") or (features.missing_features(o["x"]) if o and "x" in o else [])
            card["reasons"] = ["MODEL_UNAVAILABLE:" + body["status"]] if body["status"] != "RANKED" else (
                ["FEATURES_MISSING"] if miss else ["NO_VOLATILITY_ESTIMATE"])
            card["missing_features"] = miss
            card["history"] = _history_note(ds, view, isin, day)
            stocks.append(card)
            continue
        x = o["x"]
        card["x"] = {f: _f(x.get(f), 6) for f in features.FEATURES}
        # E19/E23: the two parts are shrunk separately, so no single ratio describes the forecast; the
        # 'shrink_factor' kept for older readers is the factor on the stock-specific part (what the levers act on)
        shrink = fc["shrink_specific"] if fc.get("shrink_specific") is not None else (
            fc["mu_shrunk"] / fc["mu_hat"] if fc["mu_hat"] else forecast.TAU_DEFAULT ** 2 / (forecast.TAU_DEFAULT ** 2 + fc["se"] ** 2))
        card["forecast"] = {k: _f(fc.get(k), 8) for k in ("mu_hat", "se", "mu_shrunk", "sigma_hat", "q10", "q50", "q90", "p_positive",
                                                       "mu_common", "mu_specific", "se_common", "se_specific",
                                                       "shrink_common", "shrink_specific", "calibration_slope",
                                                       "q10_abs", "q50_abs", "q90_abs")}
        card["forecast"].update(shrink_factor=_f(shrink, 6), tau=fc["tau"], h=cfg.h, calibration_n=fc["calibration_n"])
        card["contributions"] = _contributions(model, x)
        c = cands[isin]
        q, pc, card["costs"], card["gates"] = cost_and_gates(c, cap, policy)
        reasons_q = card["gates"]["at_quantity"]
        card["p_beats_costs"] = _f(fc["_p_above"](pc["cost_fraction"]), 4) if q > 0 else None
        sel = selected.get(isin)
        pos = plan.get("positions", {}).get(isin)
        card["allocation"] = {"selected": bool(sel), "q": sel, "value": _f(pos["value"], 2) if pos else None,
                              "costs_at_plan_q": {k: _f(pos[k]) for k in ("cost_fraction", "net_edge")} if pos else None}
        if not sel and not reasons_q:
            card["allocation"]["why_not"] = ("NOT_SELECTED_K_LIMIT" if len(selected) >= policy.K else
                                             "NOT_IN_TOP_10_POOL" if c not in passing[:10] else "NOT_SELECTED_PORTFOLIO_FIT")
        card["class"], card["reasons"] = classify(card, policy)
        if (card.get("median_value_20") or 0) < LOW_LIQUIDITY_VALUE:
            card["reasons"].append("LOW_LIQUIDITY")
        card["flip"] = _flip(card, policy, model)
        stocks.append(card)
    ranked = sorted([s for s in stocks if "gates" in s], key=edge_order)
    for i, s in enumerate(ranked, 1):
        s["rank"], s["rank_of"] = i, len(ranked)
    body["stocks"] = stocks
    body["counts"] = {k: sum(1 for s in stocks if s["class"] == k) for k in CLASSES}
    body["model"] = _model_summary(model, fit, cfg) if model else None
    body["market"] = _market_today(fit, day) if model else None
    body["plan"] = {"quantities": selected, "method": plan.get("method"), "objective": _f(plan.get("objective"))}
    digest = _digest(body)
    body["digest"] = digest
    body["created_at"] = created.isoformat()
    body["forward"] = _forward_status(calendar, entry, created)
    if write:
        path = runs / FOLDER / day.isoformat() / f"{digest[:16]}.json"
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            body["created_at"], body["forward"] = old["created_at"], old.get("forward")
        else:
            decisions._write_once(path, json.loads(json.dumps(body, default=str)))
        body["artifact"] = str(path)
    return body


def _history_note(ds, view, isin: str, day: date) -> dict:
    s = [b.day for b in view.bars(isin)]
    disc = view.discontinuities(isin)
    recent = sorted(d for d, v in disc.items() if any(k == "PRICE_DISCONTINUITY" for k, _, _ in v))
    starts = sorted(d for d, v in disc.items() if any(k == "IDENTITY_START" for k, _, _ in v))
    return {"sessions_with_bars": len(s), "first_bar": s[0].isoformat() if s else None, "needed": features.MIN_HISTORY,
            "unexplained_jumps": [d.isoformat() for d in recent][-3:], "isin_started": [d.isoformat() for d in starts][-1:]}


def _model_summary(model: forecast.Model, fit: dict, cfg) -> dict:
    m = model.to_json()
    m["beta_by_feature"] = {"intercept": model.beta[0], **{f: model.beta[j + 1] for j, f in enumerate(features.FEATURES)}}
    m["train_rows"] = fit.get("train_rows")
    m["train_days"] = fit.get("train_days")
    m["market_stats"] = {k: list(v) for k, v in (fit.get("market_stats") or {}).items()}
    m["forecasts"] = len(fit.get("fc_rows", []))
    m["coverage_missing"] = fit.get("coverage_missing")
    return m


def _market_today(fit: dict, day: date) -> dict | None:
    rows = fit.get("today") or []
    if not rows:
        return None
    o = rows[0]
    return {"raw": {f: _f(o["features"].get(f), 6) for f in features.MARKET_FEATURES},
            "z": {f: _f(o["x"].get(f), 4) for f in features.MARKET_FEATURES}}


def _validation(ds, cfg, runs: Path, promo, problems) -> dict:
    needed = features.MIN_HISTORY + cfg.train_sessions + cfg.test_sessions + cfg.holdout_sessions
    reports = registry.development_reports(runs) if runs.exists() else []
    return {"status": "PROMOTED" if promo else "UNVALIDATED", "promotion_id": promo["promotion_id"] if promo else None,
            "promotion_check": problems, "sessions_available": len(ds.sessions), "sessions_needed_for_registered_evaluation": needed,
            "development_reports": len(reports), "holdout_frozen": registry.holdout_manifest(runs) is not None,
            "note": "Forecasts come from the registered candidate trained on all resolved labels. They have not passed the "
                    "walk-forward evaluation and frozen promotion rule (spec 8.6), so treat every class as a research "
                    "screen, not a validated recommendation."}


def _forward_status(calendar, entry: date | None, created: datetime) -> dict:
    """A ranking is forward evidence only if it existed before the entry session opened."""
    from ..rules.types import Exchange, RuleUnknown
    if entry is None:
        return {"eligible": False, "why": "ENTRY_SESSION_UNKNOWN"}
    try:
        opens = calendar.session_open(Exchange.NSE, entry)
    except (RuleUnknown, AttributeError):
        opens = None
    if opens is None:
        return {"eligible": False, "why": "ENTRY_OPEN_UNKNOWN"}
    at = datetime.combine(entry, opens, IST)
    ok = created < at
    return {"eligible": ok, "entry_opens_at": at.isoformat(), "why": None if ok else "CREATED_AFTER_ENTRY_OPEN"}


# ---- reading ----------------------------------------------------------------------------------------------

def list_rankings(root: Path) -> list[dict]:
    base = decisions.runs_dir(root) / FOLDER
    out = []
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"path": str(p), "day": d.get("day"), "created_at": d.get("created_at"), "digest": d.get("digest"),
                    "status": d.get("status"), "counts": d.get("counts"), "forward": d.get("forward"), "h": d.get("h")})
    out.sort(key=lambda r: (r["day"] or "", r["created_at"] or ""))
    return out


def load(root: Path, digest: str | None = None) -> dict | None:
    """The latest ranking (by day, then creation time), or the one with this digest prefix. Integrity: the stored
    digest must equal the recomputed one, else the file is reported, not trusted."""
    items = list_rankings(root)
    if digest:
        items = [r for r in items if (r["digest"] or "").startswith(digest)]
    if not items:
        return None
    p = Path(items[-1]["path"])
    body = json.loads(p.read_text(encoding="utf-8"))
    body["integrity"] = "OK" if _digest(body) == body.get("digest") else "DIGEST_MISMATCH"
    body["artifact"] = str(p)
    return body


def forward_record(panel, calendar, root: Path, *, index_name: str = "Nifty 50") -> dict:
    """Scores rankings that were recorded before their entry session opened, once their horizon has passed: the
    realised gross excess return of each class (same label as training). Rankings created later are listed but
    never scored (their outcomes could have been known)."""
    from .sessions import exchange_sessions
    stored = set(panel.sessions())
    if not stored:
        return {"rankings": [], "note": "no panel"}
    sessions = exchange_sessions(calendar, min(stored), max(stored), stored)[0]
    out = []
    for r in list_rankings(root):
        entry = {"day": r["day"], "digest": (r["digest"] or "")[:16], "forward": (r.get("forward") or {}).get("eligible")}
        if not entry["forward"]:
            out.append(entry | {"scored": False, "why": (r.get("forward") or {}).get("why")})
            continue
        body = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
        d = date.fromisoformat(body["day"])
        by_class = {}
        pending = 0
        for s in body["stocks"]:
            if s["class"] in ("INELIGIBLE",):
                continue
            lab = labels.forward_return(panel, s["isin"], d, int(body["h"]), sessions=sessions, panel_days=stored,
                                        index_name=index_name)
            if lab.status != labels.RESOLVED:
                pending += lab.status == labels.UNRESOLVED
                continue
            by_class.setdefault(s["class"], []).append(lab.excess)
        out.append(entry | {"scored": True, "pending": pending,
                            "by_class": {k: {"n": len(v), "mean_excess": _f(sum(v) / len(v))} for k, v in by_class.items()}})
    return {"rankings": out, "note": "Gross excess log return over the horizon (before costs), only for rankings that "
                                     "existed before their entry session opened."}
