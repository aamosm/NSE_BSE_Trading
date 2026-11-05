"""Purged walk-forward evaluation with a locked holdout and the preregistered promotion rule (spec section 8).

Pipeline per fold: fit (first 80% of the training window) -> lambda and conformal residuals on the purged last
20% -> predictions on the test fold -> calibration and discrimination metrics -> a paper simulation at the policy's
capital through the gate, the allocator and EXIT.v1 with exact charges. Every trial is registered.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..common import atomic_json, now
from ..metrics.selection import deflated_sharpe_ratio, min_track_record_length, probabilistic_sharpe_ratio
from ..metrics.performance import moments
from ..rules.charges import ZERODHA_2026_11_04 as SCHEDULE, Fill, TradeKind, day_charges
from ..rules.types import Exchange, Side
from . import allocate, candidates, features, forecast, labels, monitor
from .linalg import shrunk_correlation, spearman
from .panel import Panel
from .universe import ScreenPolicy, screen


@dataclass(frozen=True, slots=True)
class Config:
    candidate: str = "A"
    h: int = 20
    train_sessions: int = 750  # about 3 years
    test_sessions: int = 125  # about 6 months
    step_sessions: int = 125
    holdout_sessions: int = 250  # locked final year; evaluated only with evaluate_holdout=True
    evaluate_holdout: bool = False
    W: float = 10_000.0
    lam_grid: tuple = forecast.LAM_GRID
    bootstrap: int = 50
    ablate: tuple = ()  # feature names forced to zero (registered ablations)
    seed: int = 0
    index_name: str = "Nifty 50"
    screen: ScreenPolicy = ScreenPolicy()
    policy: allocate.Policy | None = None  # the owner's effective policy; None = the spec 5.4 tier for W

    def __post_init__(self):
        if self.policy is not None and abs(self.policy.W - self.W) > 1e-9:
            raise ValueError("Config.W and the effective policy's capital differ")

    def effective_policy(self) -> allocate.Policy:
        return self.policy if self.policy is not None else allocate.Policy.for_capital(self.W)

    def execution_json(self) -> dict:
        return {"entry_rule": "OPEN_NEXT_SESSION.v1", "slippage_per_side": {"liquid": labels.SLIPPAGE_LIQUID,
                                                                            "other": labels.SLIPPAGE_OTHER}}

    def trial_id(self) -> str:
        body = json.dumps({"c": self.candidate, "h": self.h, "train": self.train_sessions, "test": self.test_sessions,
                           "ablate": sorted(self.ablate), "lam": list(self.lam_grid), "W": self.W,
                           "policy": self.effective_policy().digest()}, sort_keys=True)
        return f"{self.candidate}.h{self.h}." + hashlib.sha256(body.encode()).hexdigest()[:10]


@dataclass
class Dataset:
    sessions: list[date]
    rows: list[dict]  # day, isin, features, y (excess log return), sigma, label
    universe_by_day: dict[date, list[str]]
    unverified_days: dict[date, list[str]]
    closes: dict[str, dict[date, float]]
    label_exclusions: dict[str, int] = field(default_factory=dict)


def build_dataset(panel: Panel, cfg: Config, *, rule_inputs_fn=None, start: date | None = None, end: date | None = None,
                  progress=None) -> Dataset:
    """Features and labels for every (universe member, decision day) with full history. Pure functions of the panel."""
    sessions = panel.sessions(start, end)
    universe_by_day, unverified, closes, feats = {}, {}, {}, {}
    for d in sessions:
        ri = rule_inputs_fn(d) if rule_inputs_fn else None
        s = screen(panel, d, cfg.screen, ri, sessions)
        universe_by_day[d] = s.isins
        if s.unverified:
            unverified[d] = s.unverified
    isins = sorted({i for v in universe_by_day.values() for i in v})
    for n, isin in enumerate(isins):
        series = panel.series_arrays(isin)
        closes[isin] = dict(zip(series["days"], series["close"]))
        feats[isin] = features.stock_feature_rows(series)
        if progress and n % 100 == 0:
            progress(f"features {n}/{len(isins)}")
    idx = panel.index_levels(cfg.index_name)
    breadth = features.breadth_50(panel, universe_by_day, closes, sessions)
    mkt = features.market_feature_rows(idx, breadth)
    rows, excl = [], {}
    for d in sessions:
        if d not in mkt:
            continue
        for isin in universe_by_day.get(d, []):
            f = feats.get(isin, {}).get(d)
            if not f:
                continue
            lab = labels.forward_return(panel, isin, d, cfg.h, sessions=sessions, index_name=cfg.index_name)
            if lab is None:
                continue  # unresolved (too recent)
            if lab.excluded or lab.excess is None:
                excl[lab.excluded or "NO_BENCHMARK"] = excl.get(lab.excluded or "NO_BENCHMARK", 0) + 1
                continue
            fx = dict(f, **mkt[d])
            for a in cfg.ablate:
                fx[a] = 0.0
            rows.append({"day": d, "isin": isin, "features": fx, "y": lab.excess, "sigma": f["vol_20"] * math.sqrt(cfg.h),
                         "label": lab})
    return Dataset(sessions, rows, universe_by_day, unverified, closes, excl)


def folds(sessions: list[date], cfg: Config) -> list[dict]:
    """Chronological folds over session indices; the last ``holdout_sessions`` are excluded unless requested."""
    n = len(sessions) - (0 if cfg.evaluate_holdout else cfg.holdout_sessions)
    out = []
    test_start = cfg.train_sessions
    while test_start + cfg.test_sessions <= n:
        out.append({"train_start": test_start - cfg.train_sessions, "train_end": test_start - 1,
                    "test_start": test_start, "test_end": test_start + cfg.test_sessions - 1})
        test_start += cfg.step_sessions
    if cfg.evaluate_holdout and sessions:
        hs = len(sessions) - cfg.holdout_sessions
        out = [f for f in out if f["test_start"] >= hs] or [{"train_start": max(0, hs - cfg.train_sessions),
                                                            "train_end": hs - 1, "test_start": hs, "test_end": len(sessions) - 1}]
    return out


def _standardize(train_rows, test_rows):
    ms = features.market_stats(train_rows)
    return features.standardize_by_date(train_rows, ms), features.standardize_by_date(test_rows, ms)


def run_fold(ds: Dataset, fold: dict, cfg: Config, trial_id: str) -> dict:
    s = ds.sessions
    idx = {d: i for i, d in enumerate(s)}
    train = [r for r in ds.rows if fold["train_start"] <= idx[r["day"]] <= fold["train_end"]
             and labels.label_end_index(idx[r["day"]], cfg.h) < fold["test_start"] - cfg.h]  # purge + embargo
    test = [r for r in ds.rows if fold["test_start"] <= idx[r["day"]] <= fold["test_end"]]
    if len({r["day"] for r in train}) < 50 or not test:
        return {"fold": fold, "skipped": "INSUFFICIENT_ROWS", "n_train": len(train), "n_test": len(test)}
    train_s, test_s = _standardize(train, test)
    ys = features.winsorize_targets([r["y"] for r in train_s])
    for r, y in zip(train_s, ys):
        r["y"] = y
    model = forecast.fit(train_s, h=cfg.h, target_id=f"{cfg.candidate}.h{cfg.h}.v1", lam_grid=cfg.lam_grid, sessions=s,
                         bootstrap=cfg.bootstrap, seed=cfg.seed)
    preds = []
    for r in test_s:
        p = forecast.predict(model, r["x"], r["sigma"])
        if "abstain" in p:
            return {"fold": fold, "skipped": p["abstain"], "calibration_n": model.calibration_n}
        preds.append({"day": r["day"], "isin": r["isin"], "y": r["y"], **p, "price_entry": r["label"].entry_price})
    metrics = fold_metrics(preds, model)
    sim = paper_simulation(ds, preds, cfg, fold)
    return {"fold": {k: s[v].isoformat() for k, v in fold.items()}, "trial_id": trial_id, "model": model.to_json(),
            "n_train": len(train), "n_test": len(test), "metrics": metrics, "simulation": sim}


def fold_metrics(preds: list[dict], model: forecast.Model) -> dict:
    y = [p["y"] for p in preds]
    lo, hi = [p["q10"] for p in preds], [p["q90"] for p in preds]
    pos = [1 if v > 0 else 0 for v in y]
    pits = [forecast.pit(model, p["mu_hat"], p["sigma_hat"], p["y"]) for p in preds]
    by_day: dict[date, list] = {}
    for p in preds:
        by_day.setdefault(p["day"], []).append(p)
    ics = [spearman([q["mu_hat"] for q in ps], [q["y"] for q in ps]) for ps in by_day.values() if len(ps) >= 5]
    ics = [v for v in ics if not math.isnan(v)]
    pin = {f"pinball_{t}": sum(forecast.pinball(p["y"], p[f"q{int(t*100)}"], t) for p in preds) / len(preds) for t in (0.1, 0.5, 0.9)}
    uncond = sorted(y)
    from .linalg import quantile
    pin_ref = {f"pinball_{t}_unconditional": sum(forecast.pinball(v, quantile(uncond, t), t) for v in y) / len(y) for t in (0.1, 0.5, 0.9)}
    return {"n": len(preds), "coverage_80": monitor.coverage(lo, hi, y), "brier": monitor.brier([p["p_positive"] for p in preds], pos),
            "brier_skill": monitor.brier_skill([p["p_positive"] for p in preds], pos), "pit_ks": monitor.pit_ks(pits),
            "rank_ic_mean": sum(ics) / len(ics) if ics else float("nan"), "rank_ic_days": len(ics),
            "mean_y": sum(y) / len(y), "mean_mu": sum(p["mu_hat"] for p in preds) / len(preds), **pin, **pin_ref}


def _exact_round_trip(entry_value: Decimal, exit_value: Decimal, d_entry: date, d_exit: date, isin: str) -> Decimal:
    b = day_charges(SCHEDULE, [Fill(d_entry, Exchange.NSE, isin, TradeKind.DELIVERY, Side.BUY, entry_value, 1, "b")])
    s = day_charges(SCHEDULE, [Fill(d_exit, Exchange.NSE, isin, TradeKind.DELIVERY, Side.SELL, exit_value, 1, "s")])
    return b.total + s.total


def paper_simulation(ds: Dataset, preds: list[dict], cfg: Config, fold: dict) -> dict:
    """Decisions each test session with the gate + allocator + EXIT.v1; fills at the next open with slippage;
    exact charges. Positions are held for h sessions then reviewed. Returns net rupees and trade records.
    The allocator receives the effective policy of the configuration (owner caps, K, reserve, risk multiplier)."""
    from dataclasses import replace
    policy = cfg.effective_policy()
    s = ds.sessions
    by_day: dict[date, list[dict]] = {}
    for p in preds:
        by_day.setdefault(p["day"], []).append(p)
    cash = cfg.W
    positions: dict[str, dict] = {}
    trades, equity = [], []
    rejected_counts: dict[str, int] = {}
    for i in range(fold["test_start"], fold["test_end"] + 1):
        d = s[i]
        # 1. exits decided after the close of d, executed at the next open
        for isin, pos in list(positions.items()):
            pos["sessions_held"] += 1
            if pos["sessions_held"] >= cfg.h and i + 1 < len(s):
                lab = pos["label"]
                exit_day = lab.exit_day
                px = lab.exit_price / lab.factor
                exit_value = Decimal(str(round(px * pos["q"], 2)))
                entry_value = Decimal(str(round(pos["entry_price"] * pos["q"], 2)))
                cost = _exact_round_trip(entry_value, exit_value, lab.entry_day, exit_day, isin)
                pnl = float(exit_value - entry_value - cost)
                cash += float(exit_value) - float(day_charges(SCHEDULE, [Fill(exit_day, Exchange.NSE, isin, TradeKind.DELIVERY,
                                                                                Side.SELL, exit_value, 1, "s")]).total)
                trades.append({"isin": isin, "entry": lab.entry_day.isoformat(), "exit": exit_day.isoformat(), "q": pos["q"],
                               "entry_price": round(pos["entry_price"], 4), "exit_price": round(px, 4), "gross": lab.gross,
                               "net_pnl": round(pnl, 2), "cost": float(cost), "mu_shrunk": pos["mu"], "q10": pos["q10"]})
                del positions[isin]
        # 2. entries: candidates from today's forecasts
        if len(positions) < policy.K and d in by_day:
            cands, lookup = [], {}
            for p in by_day[d]:
                if p["isin"] in positions:
                    continue
                lab = next((r["label"] for r in ds.rows if r["isin"] == p["isin"] and r["day"] == d), None)
                if lab is None:
                    continue
                slip = labels.slippage_for(0)  # conservative: 0.25% per side until a liquidity tier is stored with the row
                c = allocate.Candidate(p["isin"], p["price_entry"] / (1 + slip), p["mu_shrunk"], p["sigma_hat"], 2 * slip, p["q10"])
                cands.append(c)
                lookup[p["isin"]] = (p, lab)
            if cands:
                rets = [[ds.closes[c.isin].get(s[k], float("nan")) for k in range(max(0, i - 60), i + 1)] for c in cands]
                logr = []
                for r in rets:
                    xs = [math.log(r[k] / r[k - 1]) if r[k] > 0 and r[k - 1] > 0 else 0.0 for k in range(1, len(r))]
                    logr.append(xs)
                corr = shrunk_correlation(logr, 0.5) if len(cands) > 1 else [[1.0]]
                held_value = sum(pos["q"] * pos["entry_price"] for pos in positions.values())
                avail = cash - policy.reserve_fraction * cfg.W
                sub_policy = replace(policy, K=policy.K - len(positions))
                out = allocate.plan(cands, corr, sub_policy, max(0.0, avail - 0.0 * held_value))
                for code in {v[0] for v in out["rejected"].values() if v}:
                    rejected_counts[code] = rejected_counts.get(code, 0) + 1
                for isin, q in out["quantities"].items():
                    p, lab = lookup[isin]
                    entry_value = Decimal(str(round(lab.entry_price * q, 2)))
                    buy_cost = float(day_charges(SCHEDULE, [Fill(lab.entry_day, Exchange.NSE, isin, TradeKind.DELIVERY, Side.BUY,
                                                                   entry_value, 1, "b")]).total)
                    cash -= float(entry_value) + buy_cost
                    positions[isin] = {"q": q, "entry_price": lab.entry_price, "label": lab, "sessions_held": 0,
                                       "mu": p["mu_shrunk"], "q10": p["q10"]}
        mark = cash + sum(pos["q"] * ds.closes[isin].get(d, pos["entry_price"]) for isin, pos in positions.items())
        equity.append(round(mark, 2))
    open_value = sum(pos["q"] * pos["entry_price"] for pos in positions.values())
    net = sum(t["net_pnl"] for t in trades)
    rets = [t["net_pnl"] / (t["q"] * t["entry_price"]) for t in trades]
    sr = (sum(rets) / len(rets)) / (math.sqrt(sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / (len(rets) - 1))) \
        if len(rets) > 2 and any(r != rets[0] for r in rets) else float("nan")
    return {"net_rupees_realized": round(net, 2), "trades": trades, "n_trades": len(trades), "hit_rate": (sum(1 for r in rets if r > 0) / len(rets)) if rets else float("nan"),
            "open_positions_value": round(open_value, 2), "ending_cash": round(cash, 2), "equity_curve": equity,
            "max_drawdown": _max_dd(equity), "per_trade_sharpe": sr, "rejected": rejected_counts,
            "time_in_cash": sum(1 for e in equity if e == cash) / len(equity) if equity else float("nan")}


def jsonable(x):
    """NaN/inf -> None (undefined stays undefined), Decimal/date -> str, dataclasses -> dict."""
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (Decimal, date)):
        return str(x) if isinstance(x, Decimal) else x.isoformat()
    if hasattr(x, "__dataclass_fields__"):
        return jsonable({f: getattr(x, f) for f in x.__dataclass_fields__})
    return x


def _max_dd(curve: list[float]) -> float:
    peak, dd = -float("inf"), 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd


def walk_forward(panel: Panel, cfg: Config, *, out_dir: Path, rule_inputs_fn=None, progress=print) -> dict:
    spec = candidates.require(cfg.candidate, cfg.h, cfg.ablate)  # B/C and unregistered trials stop here
    ds = build_dataset(panel, cfg, rule_inputs_fn=rule_inputs_fn, progress=progress)
    trial_id = cfg.trial_id()
    fs = folds(ds.sessions, cfg)
    results = [run_fold(ds, f, cfg, trial_id) for f in fs]
    report = summarize(results, cfg, ds, trial_id)
    report["candidate_spec"] = candidates.describe(spec, cfg.ablate)
    report["policy"] = cfg.effective_policy().to_json()
    report["policy_digest"] = cfg.effective_policy().digest()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = jsonable(report)
    atomic_json(out_dir / f"{trial_id}.json", report)
    return report


def summarize(results: list[dict], cfg: Config, ds: Dataset, trial_id: str) -> dict:
    done = [r for r in results if "skipped" not in r]
    net_by_fold = [r["simulation"]["net_rupees_realized"] for r in done]
    all_trades = [t for r in done for t in r["simulation"]["trades"]]
    rets = [t["net_pnl"] / (t["q"] * t["entry_price"]) for t in all_trades]
    pooled = {}
    if len(rets) > 2:
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        sr = m / sd if sd > 0 else float("nan")
        try:
            skew, kurt = moments(rets)
        except Exception:
            skew, kurt = 0.0, 3.0
        pooled = {"mean_net_return": m, "sd": sd, "sharpe_per_trade": sr, "skew": skew, "kurtosis": kurt}
        if not math.isnan(sr):
            try:
                pooled["psr_vs_zero"] = probabilistic_sharpe_ratio(sr, 0.0, len(rets), skew, kurt)
                pooled["min_track_record_95"] = min_track_record_length(sr, 0.0, skew, kurt) if sr > 0 else None
            except Exception as e:
                pooled["psr_error"] = type(e).__name__
    coverage = [r["metrics"]["coverage_80"] for r in done]
    bss = [r["metrics"]["brier_skill"] for r in done if not math.isnan(r["metrics"]["brier_skill"])]
    return {"trial_id": trial_id, "generated_at": now().isoformat(),
            "config": {f.name: (list(getattr(cfg, f.name)) if isinstance(getattr(cfg, f.name), tuple) else getattr(cfg, f.name))
                       for f in fields(cfg) if f.name not in ("screen", "policy")},
            "sessions": [ds.sessions[0].isoformat(), ds.sessions[-1].isoformat()] if ds.sessions else [],
            "rows": len(ds.rows), "label_exclusions": ds.label_exclusions,
            "unverified_days": len(ds.unverified_days), "folds": results, "net_rupees_by_fold": net_by_fold,
            "net_rupees_total": round(sum(net_by_fold), 2), "folds_positive": sum(1 for v in net_by_fold if v > 0),
            "folds_done": len(done), "n_trades": len(all_trades), "pooled": pooled,
            "coverage_80_mean": sum(coverage) / len(coverage) if coverage else float("nan"),
            "brier_skill_mean": sum(bss) / len(bss) if bss else float("nan"),
            "profitability_proven": False, "note": "Research diagnostic. Promotion requires the rule in spec section 8.6 "
                                                   "with the registered trial count, stresses and the locked holdout."}


def promotion(report: dict, *, n_trials: int, sr_variance_across_trials: float, stresses_passed: bool | None = None,
              holdout_net: float | None = None) -> dict:
    """Spec 8.6. Returns PROMOTED / REJECT / INSUFFICIENT EVIDENCE with every criterion's value."""
    crit = {}
    p = report.get("pooled", {})
    crit["net_positive_pooled"] = report.get("net_rupees_total", 0) > 0
    crit["folds_positive_60pct"] = report.get("folds_done", 0) > 0 and report.get("folds_positive", 0) / report["folds_done"] >= 0.6
    dsr = None
    if "sharpe_per_trade" in p and not math.isnan(p["sharpe_per_trade"]) and report.get("n_trades", 0) > 2:
        try:
            dsr = deflated_sharpe_ratio(p["sharpe_per_trade"], report["n_trades"], p["skew"], p["kurtosis"],
                                        n_trials=max(2, n_trials), sr_variance_across_trials=sr_variance_across_trials)
        except Exception:
            dsr = None
    crit["dsr_95"] = dsr is not None and dsr >= 0.95
    crit["coverage_80_in_band"] = 0.72 <= (report.get("coverage_80_mean") or 0) <= 0.88
    crit["brier_skill_positive"] = (report.get("brier_skill_mean") or 0) > 0
    crit["stresses_passed"] = bool(stresses_passed)
    crit["holdout_net_positive"] = holdout_net is not None and holdout_net > 0
    mtrl = p.get("min_track_record_95")
    enough = mtrl is not None and report.get("n_trades", 0) >= mtrl
    crit["n_trades_ge_mintrl"] = enough
    insufficient = (not enough) or stresses_passed is None or holdout_net is None or dsr is None
    verdict = "PROMOTED" if all(crit.values()) else ("INSUFFICIENT EVIDENCE" if insufficient else "REJECT")
    return {"verdict": verdict, "criteria": crit, "dsr": dsr, "min_track_record_95": mtrl, "n_trades": report.get("n_trades", 0),
            "pbo": "not computed here: run metrics.selection.probability_of_backtest_overfitting on the per-trial return matrix"}
