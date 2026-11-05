"""Today's paper decision from the panel, recorded under one decision id whatever the outcome.

Order of checks (each failure is a durable WAIT, spec 5.2): registered candidate -> family enabled by the owner ->
verified promotion record for (candidate, horizon, effective policy) -> panel history -> resolved labels ->
calibration -> gate and allocator at whole-share quantities. Forecasts and a hypothetical plan computed without
a verified promotion are stored as diagnostics beside the decision, never as the decision. There is no flag that
promotes a model: only ``registry.verified_promotion`` can.
"""
from __future__ import annotations

import math
from pathlib import Path

from .. import decisions
from . import allocate, candidates, evaluate, features, forecast, labels, registry
from .linalg import shrunk_correlation
from .panel import Panel
from .universe import screen


def run(panel: Panel | None, cfg: evaluate.Config, *, root: Path, origin: str, families: dict | None = None,
        rule_inputs_fn=None, bootstrap: int = 50, decision_id: str | None = None, extra: dict | None = None) -> dict:
    """Decide for the latest panel session and persist the record. Returns the timeline entry plus the record."""
    policy = cfg.effective_policy()
    runs = decisions.runs_dir(root)
    sessions = panel.sessions() if panel is not None else []
    day = sessions[-1] if sessions else __import__("marketlab.common", fromlist=["now"]).now().date()
    body = {"day": day.isoformat(), "candidate": cfg.candidate, "h": cfg.h, "policy": policy.to_json(),
            "policy_digest": policy.digest(), "execution": cfg.execution_json(), **(extra or {})}

    def finish(action, reasons, diagnostics=None, **more):
        rec = dict(body, action=action, reasons=reasons, **more)
        entry = decisions.record(root, rec, origin=origin, decision_id=decision_id, diagnostics=diagnostics, runs=runs)
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
    ds = evaluate.build_dataset(panel, cfg, rule_inputs_fn=rule_inputs_fn)  # resolved labels only
    if len({r["day"] for r in ds.rows}) < 60:
        return finish("WAIT", reasons + ["INSUFFICIENT_RESOLVED_LABELS"], rows=len(ds.rows))
    train_s = features.standardize_by_date(ds.rows, features.market_stats(ds.rows))
    ys = features.winsorize_targets([r["y"] for r in train_s])
    for r, y in zip(train_s, ys):
        r["y"] = y
    model = forecast.fit(train_s, h=cfg.h, target_id=f"{cfg.candidate}.h{cfg.h}.v1", lam_grid=cfg.lam_grid, sessions=sessions,
                         bootstrap=bootstrap, seed=cfg.seed)
    s = screen(panel, day, cfg.screen, rule_inputs_fn(day) if rule_inputs_fn else None, sessions)
    idx = panel.index_levels(cfg.index_name)
    breadth = features.breadth_50(panel, {day: s.isins}, {i: {day: panel.bars(i, day, day)[0].close for i in s.isins if panel.bars(i, day, day)} for i in s.isins}, sessions)
    mkt = features.market_feature_rows(idx, breadth).get(day)
    today_rows = []
    for isin in s.isins:
        f = features.stock_feature_rows(panel.series_arrays(isin)).get(day)
        if f and mkt:
            today_rows.append({"day": day, "isin": isin, "features": dict(f, **mkt), "sigma": f["vol_20"] * math.sqrt(cfg.h)})
    today_s = features.standardize_by_date(today_rows, features.market_stats(ds.rows)) if today_rows else []
    fc_rows, cands = [], []
    for r in today_s:
        p = forecast.predict(model, r["x"], r["sigma"])
        bar = panel.bars(r["isin"], day, day)[0]
        slip = labels.slippage_for(bar.value)
        fc_rows.append({"isin": r["isin"], "symbol": bar.symbol, "close": bar.close, **p, "slippage": 2 * slip})
        if "abstain" not in p:
            cands.append(allocate.Candidate(r["isin"], bar.close, p["mu_shrunk"], p["sigma_hat"], 2 * slip, p["q10"], bar.symbol))
    plan = {"quantities": {}, "note": "no candidates"}
    if cands:
        rets = []
        for c in cands:
            bars = panel.bars(c.isin, sessions[max(0, len(sessions) - 61)], day)
            rets.append([math.log(b.close / b.prev_close) if b.close > 0 and b.prev_close > 0 else 0.0 for b in bars])
        corr = shrunk_correlation(rets, 0.5) if len(cands) > 1 else [[1.0]]
        plan = allocate.plan(cands, corr, policy, policy.W * (1 - policy.reserve_fraction))
    fc_rows.sort(key=lambda f: -(f.get("mu_shrunk") or -1))
    if model.calibration_n < forecast.MIN_CALIBRATION:
        reasons.append("INSUFFICIENT_CALIBRATION")
    if not plan.get("quantities"):
        reasons.append("NO_CANDIDATE_PASSES_GATE")
    if not reasons:
        reasons.append("FORWARD_PAPER_LEDGER_NOT_BUILT")  # a promoted plan still has nowhere to go yet
    diagnostics = {"model": model.to_json(), "forecasts": fc_rows[:50], "plan": plan,
                   "plan_status": "DIAGNOSTIC_NOT_PROMOTED" if not promo else "DIAGNOSTIC_LEDGER_MISSING"}
    return finish("WAIT", reasons, diagnostics=evaluate.jsonable(diagnostics), model_id=model.target_id,
                  universe={"kept": len(s.isins), "excluded": s.stats, "unverified": s.unverified},
                  forecasts=len(fc_rows), plan_quantities=plan.get("quantities", {}))
