"""Today's paper decision from the panel: fit on resolved history, forecast the latest universe, allocate.

Every output is labelled with its promotion state. Until a candidate is PROMOTED by the evaluation plan the
decision is recorded as WAIT with the forecasts attached as research diagnostics (spec 5.2, gate 3).
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from ..common import atomic_json, now
from . import allocate, evaluate, features, forecast, labels
from .linalg import shrunk_correlation
from .panel import Panel
from .universe import screen


def latest_decision(panel: Panel, cfg: evaluate.Config, *, promoted: bool, rule_inputs_fn=None, out_dir: Path | None = None,
                    bootstrap: int = 50) -> dict:
    sessions = panel.sessions()
    if len(sessions) < cfg.train_sessions // 2:
        return {"action": "WAIT", "reasons": ["INSUFFICIENT_HISTORY"], "sessions": len(sessions)}
    day = sessions[-1]
    ds = evaluate.build_dataset(panel, cfg, rule_inputs_fn=rule_inputs_fn)  # resolved labels only
    if len({r["day"] for r in ds.rows}) < 60:
        return {"action": "WAIT", "reasons": ["INSUFFICIENT_RESOLVED_LABELS"], "rows": len(ds.rows), "day": day.isoformat()}
    train_s = features.standardize_by_date(ds.rows, features.market_stats(ds.rows))
    ys = features.winsorize_targets([r["y"] for r in train_s])
    for r, y in zip(train_s, ys):
        r["y"] = y
    model = forecast.fit(train_s, h=cfg.h, target_id=f"{cfg.candidate}.h{cfg.h}.v1", lam_grid=cfg.lam_grid, sessions=sessions,
                         bootstrap=bootstrap, seed=cfg.seed)
    # features for the latest session (labels unresolved): recompute rows for today's universe
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
    forecasts, cands = [], []
    for r in today_s:
        p = forecast.predict(model, r["x"], r["sigma"])
        bar = panel.bars(r["isin"], day, day)[0]
        slip = labels.slippage_for(bar.value)
        fc = {"isin": r["isin"], "symbol": bar.symbol, "close": bar.close, **p, "slippage": 2 * slip}
        forecasts.append(fc)
        if "abstain" not in p:
            cands.append(allocate.Candidate(r["isin"], bar.close, p["mu_shrunk"], p["sigma_hat"], 2 * slip, p["q10"], bar.symbol))
    policy = allocate.Policy.for_capital(cfg.W)
    plan = {"quantities": {}, "note": "no candidates"}
    if cands:
        rets = []
        for c in cands:
            bars = panel.bars(c.isin, sessions[max(0, len(sessions) - 61)], day)
            rets.append([math.log(b.close / b.prev_close) if b.close > 0 and b.prev_close > 0 else 0.0 for b in bars])
        corr = shrunk_correlation(rets, 0.5) if len(cands) > 1 else [[1.0]]
        plan = allocate.plan(cands, corr, policy, cfg.W * (1 - policy.reserve_fraction))
    forecasts.sort(key=lambda f: -(f.get("mu_shrunk") or -1))
    reasons = []
    if not promoted:
        reasons.append("MODEL_NOT_PROMOTED")
    if model.calibration_n < forecast.MIN_CALIBRATION:
        reasons.append("INSUFFICIENT_CALIBRATION")
    if not plan.get("quantities"):
        reasons.append("NO_CANDIDATE_PASSES_GATE")
    out = {"day": day.isoformat(), "generated_at": now().isoformat(), "action": "WAIT" if reasons else "PAPER_PLAN",
           "reasons": reasons, "candidate": cfg.candidate, "h": cfg.h, "model": model.to_json(),
           "universe": {"kept": len(s.isins), "excluded": s.stats, "unverified": s.unverified},
           "forecasts": forecasts[:50], "plan": plan, "policy": {"W": policy.W, "K": policy.K, "cap_fraction": policy.cap_fraction,
                                                                "reserve_fraction": policy.reserve_fraction, "gamma": policy.risk_aversion()},
           "simulated": True, "live_orders": False}
    out = evaluate.jsonable(out)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(out_dir / f"{day.isoformat()}_{cfg.candidate}_h{cfg.h}.json", out)
    return out
