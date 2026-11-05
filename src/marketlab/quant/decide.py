"""Today's paper decision from the panel, recorded under one decision id whatever the outcome.

Order of checks (each failure is a durable WAIT, spec 5.2): registered candidate -> family enabled by the owner ->
verified promotion record for (candidate, horizon, effective policy) -> panel history -> resolved labels ->
calibration -> feature coverage -> gate and allocator at whole-share quantities.

The live decision uses the replay path itself: ``evaluate.build_dataset`` over the panel, and the latest session's
rows of that dataset (same screen, same features, same breadth over 50 exchange sessions). Rule inputs are those
RECEIVED before the decision (the replay may use reconstructed availability instead, labelled as such).
Forecasts and a hypothetical plan computed without a verified promotion are stored as diagnostics beside the
decision, never as the decision. There is no flag that promotes a model: only ``registry.verified_promotion``.
"""
from __future__ import annotations

from pathlib import Path

from .. import decisions
from ..common import now
from . import allocate, candidates, evaluate, features, forecast, labels, registry, replay
from .ledger import reservation
from .panel import Panel


def run(panel: Panel | None, cfg: evaluate.Config, *, root: Path, origin: str, families: dict | None = None,
        rule_inputs_fn=None, calendar=None, bootstrap: int = 50, decision_id: str | None = None,
        extra: dict | None = None, actions=None) -> dict:
    """Decide for the latest panel session and persist the record. Returns the timeline entry plus the record."""
    policy = cfg.effective_policy()
    runs = decisions.runs_dir(root)
    sessions = panel.sessions() if panel is not None else []
    day = sessions[-1] if sessions else now().date()
    body = {"day": day.isoformat(), "candidate": cfg.candidate, "h": cfg.h, "policy": policy.to_json(),
            "policy_digest": policy.digest(), "execution": cfg.execution_json(), **(extra or {})}

    def finish(action, reasons, diagnostics=None, **more):
        rec = dict(body, action=action, reasons=reasons, **more)
        entry = decisions.record(root, rec, origin=origin, decision_id=decision_id,
                                 diagnostics=evaluate.jsonable(diagnostics) if diagnostics is not None else None, runs=runs)
        return entry | {"record": decisions.load(root, entry["decision_id"], runs)}

    try:
        spec = candidates.require(cfg.candidate, cfg.h, cfg.ablate)
    except candidates.Unimplemented as e:
        return finish("WAIT", ["UNIMPLEMENTED_CANDIDATE"], detail=str(e))
    body["candidate_spec"] = candidates.describe(spec, cfg.ablate)
    if families is not None and not families.get(spec.family, False):
        return finish("WAIT", ["FAMILY_DISABLED_BY_OWNER"])
    promo, problems = registry.verified_promotion(runs, cfg.candidate, cfg.h, policy.digest())
    reasons = [] if promo else ["MODEL_NOT_PROMOTED"]
    body["promotion_id"] = promo["promotion_id"] if promo else None
    body["promotion_check"] = problems
    if panel is None:
        return finish("WAIT", reasons + ["PANEL_NOT_BUILT"])
    if len(sessions) < cfg.train_sessions // 2:
        return finish("WAIT", reasons + ["INSUFFICIENT_HISTORY"], sessions=len(sessions))
    if calendar is None:
        raise ValueError("a calendar is required to count exchange sessions")
    ds = evaluate.build_dataset(panel.view(None), cfg, calendar=calendar, rule_inputs_fn=rule_inputs_fn, actions=actions)
    u = ds.universe.get(day)
    body["universe"] = ({"kept": len(u.isins), "excluded": u.stats, "unverified": u.unverified,
                         "availability": u.availability} if u else {"kept": 0, "unverified": ["DAY_NOT_A_SESSION"]})
    body["data"] = {"manifest_hash": ds.manifest_hash, "missing_sessions": len(ds.missing_sessions),
                    "session_basis": {str(k): v for k, v in ds.session_basis.items()}}
    complete = features.rank_stock_features([o for o in ds.opportunities if not o["missing"]])
    train = [o for o in complete if o["label"].status == labels.RESOLVED]
    if len({o["day"] for o in train}) < 60:
        return finish("WAIT", reasons + ["INSUFFICIENT_RESOLVED_LABELS"], rows=len(train))
    ms = features.market_stats(train)
    train = [o for o in features.scale_market_features(train, ms) if not features.missing_features(o["x"])]
    today_all = [o for o in ds.opportunities if o["day"] == day]
    today = features.scale_market_features([o for o in complete if o["day"] == day], ms)
    ys = features.winsorize_targets([o["label"].excess for o in train])
    fit_rows = [{"day": o["day"], "isin": o["isin"], "x": o["x"], "y": y, "sigma": o["sigma"]} for o, y in zip(train, ys)]
    model = forecast.fit(fit_rows, h=cfg.h, target_id=f"{cfg.candidate}.h{cfg.h}.v2", lam_grid=cfg.lam_grid,
                         sessions=ds.sessions, bootstrap=bootstrap, seed=cfg.seed)
    fc_rows, todays = [], {}
    coverage_missing = len(today_all) - len(today)
    for o in today:
        if features.missing_features(o["x"]) or not (o["sigma"] > 0):
            coverage_missing += 1
            continue
        p = forecast.predict(model, o["x"], o["sigma"])
        row = {"isin": o["isin"], "symbol": o["symbol"], "close": o["ref_close"], **p,
               "slippage": 2 * labels.slippage_for(o["median_value"])}
        fc_rows.append(row)
        if "abstain" not in p:
            z = model.z_sorted
            todays[o["isin"]] = dict(p, ref_close=o["ref_close"], symbol=o["symbol"], median_value=o["median_value"],
                                     _p_above=lambda c, mu=p["mu_hat"], sg=p["sigma_hat"], z=z:
                                     forecast.conformal_probability_above(z, (c - mu) / sg))
    if promo is not None and model.calibration_n >= forecast.MIN_CALIBRATION:
        return _paper_decision(panel, cfg, policy, ds, day, todays, model, fc_rows, coverage_missing, calendar, root,
                               actions, finish)
    plan, intents = {"quantities": {}, "note": "no candidates"}, []
    cands = [replay.candidate_for(i, fc, cfg.execution) for i, fc in todays.items()]
    passing = [c for c in cands if allocate.entry_gate(c, policy)[0]]
    if passing:
        passing.sort(key=lambda c: -(c.mu - allocate.VARIABLE_ROUND_TRIP - c.slippage))
        passing = passing[:10]
        corr = replay._corr(panel, [c.isin for c in passing], ds.sessions, len(ds.sessions) - 1)
        plan = allocate.plan(passing, corr, policy, policy.W * (1 - policy.reserve_fraction))
        for isin, q in plan["quantities"].items():
            fc, pos = todays[isin], plan["positions"][isin]
            limit = fc["ref_close"] * (1 + cfg.execution.max_entry_gap)
            intents.append({"isin": isin, "symbol": fc["symbol"], "q": q, "decision_close": fc["ref_close"],
                            "limit": round(limit, 4), "cash_blocked": str(reservation(q, limit)),
                            "costs_at_q": {k: pos[k] for k in ("value", "charges", "slippage", "cost_fraction", "net_edge")},
                            "p_active_beats_costs_at_q": fc["_p_above"](pos["cost_fraction"])})
    else:
        plan["rejected"] = {c.isin: allocate.entry_gate(c, policy)[1] for c in cands}
    fc_rows.sort(key=lambda f: -(f.get("mu_shrunk") or -1))
    if model.calibration_n < forecast.MIN_CALIBRATION:
        reasons.append("INSUFFICIENT_CALIBRATION")
    if coverage_missing and not fc_rows:
        reasons.append("FEATURE_COVERAGE")
    if not plan.get("quantities"):
        reasons.append("NO_CANDIDATE_PASSES_GATE")
    if not reasons:
        reasons.append("FORWARD_PAPER_LEDGER_NOT_BUILT")  # a promoted plan still has nowhere to go yet
    diagnostics = {"model": model.to_json(), "forecasts": fc_rows[:50], "plan": plan, "intents": intents,
                   "feature_coverage_missing": coverage_missing,
                   "plan_status": "DIAGNOSTIC_NOT_PROMOTED" if not promo else "DIAGNOSTIC_LEDGER_MISSING"}
    return finish("WAIT", reasons, diagnostics=diagnostics, model_id=model.target_id, forecasts=len(fc_rows),
                  plan_quantities=plan.get("quantities", {}))


def _paper_decision(panel, cfg, policy, ds, day, todays, model, fc_rows, coverage_missing, calendar, root, actions, finish):
    """With a verified promotion: rebuild the forward paper ledger through today, run EXIT.v1 reviews and the
    allocator against its real holdings, free cash and pending intents, and record the new orders (PAPER_PLAN).
    Tomorrow's rebuild executes them at the next stored open under EXEC.v1."""
    from . import paper
    from .ledger import Ledger
    built = paper.rebuild(panel, calendar, root, day, actions=actions, h=cfg.h)
    led = built["ledger"] if built else Ledger(policy.W, cfg.execution)
    k = len(ds.sessions) - 1
    before_intents = set(led.intents)
    before_exits = {i for i, lot in led.lots.items() if lot.exit_pending}
    excl = ds.universe[day].excluded if day in ds.universe else {}
    replay.review_exits(led, k, day, todays, excl, policy, cfg.h, cfg.execution)
    planned = replay.plan_entries(led, panel, ds.sessions, k, day, todays, policy, cfg.execution)
    orders = {"intents": [paper.intent_to_json(i) for iid, i in led.intents.items() if iid not in before_intents],
              "exits": [{"isin": i, "reason": lot.exit_reason} for i, lot in led.lots.items()
                        if lot.exit_pending and i not in before_exits]}
    diagnostics = {"model": model.to_json(), "forecasts": fc_rows[:50], "allocation": planned,
                   "feature_coverage_missing": coverage_missing, "plan_status": "PAPER_ORDERS"}
    common = dict(diagnostics=diagnostics, model_id=model.target_id, forecasts=len(fc_rows), index_name=cfg.index_name,
                  ledger_before=paper.state(led) if built else {"note": "first paper decision: no account before it"})
    if orders["intents"] or orders["exits"]:
        return finish("PAPER_PLAN", ["COST_AND_RISK_GATES_PASSED"], orders=orders, **common)
    return finish("WAIT", ["NO_CANDIDATE_PASSES_GATE"], **common)
