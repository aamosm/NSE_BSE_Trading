"""Purged walk-forward evaluation with a frozen holdout, a causal paper ledger and the preregistered promotion rule
(spec section 8).

Pipeline:
1. ``build_dataset`` over a panel VIEW: exchange sessions from the calendar; for every decision session the dated
   universe (rule files of the entry session) is fixed first; features and decision-time fields are attached;
   labels are attached last and never remove an opportunity.
2. Per fold: stock features ranked over the whole decision-time cross-section of each date; market features
   scaled with training statistics; ridge + split-conformal fit on resolved training labels whose exit date
   precedes the test start minus an h-session embargo; forecasts for every test opportunity.
3. Calibration metrics on the test opportunities whose labels resolved (references fitted on training data).
4. ``replay.simulate``: intents frozen after each close, fills at later opens under EXEC.v1, EXIT.v1 reviews,
   exact charges, settlement, daily NAV, liquidation valuation of open positions at the fold end; stress runs.
5. The report is written once to its own immutable file; development runs see the panel only up to the day
   before the frozen holdout start.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, fields, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ..common import now
from ..metrics.performance import moments
from ..metrics.selection import (MetricUnavailable, deflated_sharpe_ratio, min_track_record_length,
                                 probabilistic_sharpe_ratio, probability_of_backtest_overfitting)
from . import allocate, candidates, features, forecast, labels, monitor, registry, replay
from .ledger import ExecutionPolicy
from .linalg import quantile, spearman
from .panel import Panel
from .sessions import exchange_sessions, next_session
from .universe import ScreenPolicy, Screened, screen

MIN_COVERAGE_N = 200  # fewer resolved test forecasts: the calibration test is inconclusive


@dataclass(frozen=True, slots=True)
class Config:
    candidate: str = "A"
    h: int = 20
    train_sessions: int = 750  # about 3 years
    test_sessions: int = 125  # about 6 months
    step_sessions: int = 125
    holdout_sessions: int = 250  # length used when the holdout is frozen (registry.freeze_holdout)
    evaluate_holdout: bool = False
    W: float = 10_000.0
    lam_grid: tuple = forecast.LAM_GRID
    bootstrap: int = 50
    ablate: tuple = ()  # feature names forced to zero (registered ablations only)
    seed: int = 0
    index_name: str = "Nifty 50"
    screen: ScreenPolicy = ScreenPolicy()
    policy: allocate.Policy | None = None  # the owner's effective policy; None = the spec 5.4 tier for W
    execution: ExecutionPolicy = ExecutionPolicy()
    availability: str = "RECONSTRUCTED"  # rule-input availability in replay (spec 2.1)

    def __post_init__(self):
        if self.policy is not None and abs(self.policy.W - self.W) > 1e-9:
            raise ValueError("Config.W and the effective policy's capital differ")

    def effective_policy(self) -> allocate.Policy:
        return self.policy if self.policy is not None else allocate.Policy.for_capital(self.W)

    def execution_json(self) -> dict:
        return self.execution.to_json()

    def trial_id(self) -> str:
        body = json.dumps({"c": self.candidate, "h": self.h, "train": self.train_sessions, "test": self.test_sessions,
                           "ablate": sorted(self.ablate), "lam": list(self.lam_grid), "W": self.W,
                           "policy": self.effective_policy().digest(), "execution": self.execution.digest(),
                           "availability": self.availability}, sort_keys=True)
        return f"{self.candidate}.h{self.h}." + hashlib.sha256(body.encode()).hexdigest()[:10]


@dataclass
class Dataset:
    sessions: list[date]
    panel_days: set[date]
    missing_sessions: list[date]
    session_basis: dict[int, str]
    universe: dict[date, Screened]
    opportunities: list[dict]
    label_counts: dict[str, int] = field(default_factory=dict)
    feature_missing: int = 0
    manifest_hash: str = ""
    end: date | None = None
    lineage: dict = field(default_factory=dict)  # isin -> ISIN chain whose bars feed its features (listed successions)

    @property
    def rows(self) -> list[dict]:
        """Training-eligible rows: complete features and a resolved label (statistical selection only)."""
        return [o for o in self.opportunities if not o["missing"] and o["label"].status == labels.RESOLVED]


def security_history(view: Panel, isin: str, disc_all: dict, actions=None) -> dict:
    """The price history used for one security's features at decision time.

    Without ``actions`` (no listed-action registry): the ISIN's own bars; every PRICE_DISCONTINUITY day is bad (its
    windows are incomplete). With ``actions``: listed, ratio-consistent splits/bonuses become return and level
    factors instead of bad days, and when the ISIN began on an ex-date through such an action (IDENTITY_START whose
    predecessor carries the listed factor), the predecessor's bars are prepended, so a split that issued a new ISIN
    does not erase a year of history. An unexplained ISIN change is never stitched. Only bars up to the view's end
    are read, so the history never contains a later price."""
    chain = [isin]
    links = []
    if actions is not None:
        cur = isin
        while True:
            starts = sorted((d, v[2]) for d, vs in disc_all.get(cur, {}).items() for v in vs if v[0] == "IDENTITY_START")
            if not starts:
                break
            d, prev = starts[0]
            if prev in chain or actions.factor(prev, d) is None:
                break  # an unexplained identity change: keep the new ISIN's own history only
            links.append((prev, d))
            chain.insert(0, prev)
            cur = prev
    parts = [view.series_arrays(i) for i in chain]
    if len(parts) == 1:
        series = parts[0]
    else:
        series = {k: [] for k in parts[0]}
        for i, part in enumerate(parts):
            cut = links[len(links) - 1 - i][1] if i < len(parts) - 1 else None  # the successor's first day
            for j, d in enumerate(part["days"]):
                if cut is not None and d >= cut:
                    break
                for k in series:
                    series[k].append(part[k][j])
    rf, lf = {}, {}
    if actions is not None:
        for member in chain:
            for d in actions.days_for(member):
                f = actions.factor(member, d)
                if f is not None:
                    lf[d] = lf.get(d, 1.0) * f
                    g = actions.return_factor(member, d)
                    if g is not None:
                        rf[d] = rf.get(d, 1.0) * g
    bad = set()
    for member in chain:
        for d, v in disc_all.get(member, {}).items():
            if any(k == "PRICE_DISCONTINUITY" for k, _, _ in v) and d not in lf:
                bad.add(d)
    return {"series": series, "bad_days": bad, "return_factors": rf, "level_factors": lf, "lineage": chain}


def build_dataset(view: Panel, cfg: Config, *, calendar, rule_inputs_fn=None, listed_actions=None, progress=None,
                  actions=None) -> Dataset:
    """The opportunity set first (decision-time only), then features, then labels."""
    panel_days = set(view.sessions())
    if not panel_days:
        return Dataset([], set(), [], {}, {}, [], end=view.end_limit)
    sessions, basis = exchange_sessions(calendar, min(panel_days), max(panel_days), panel_days)
    missing = [d for d in sessions if d not in panel_days]
    decision_days = [d for d in sessions if d in panel_days]
    universe: dict[date, Screened] = {}
    for d in decision_days:
        entry = next_session(calendar, d, sessions)
        ri = rule_inputs_fn(entry) if (rule_inputs_fn and entry) else None
        universe[d] = screen(view, d, cfg.screen, ri, sessions, panel_days)
    isins = sorted({i for s in universe.values() for i in s.isins})
    feats, closes, data = {}, {}, {}
    unchecked = view.unchecked_days()
    index = view.index_levels(cfg.index_name)
    disc_all = view.discontinuities()
    lineage = {}
    for n, isin in enumerate(isins):
        hist = security_history(view, isin, disc_all, actions)
        series = hist["series"]
        if len(hist["lineage"]) > 1:
            lineage[isin] = hist["lineage"]
        if hist["level_factors"]:  # breadth compares a close with its own 50-session average: same units needed
            acc, cl = 0.0, []
            for d, c in zip(series["days"], series["close"]):
                acc += math.log(hist["level_factors"][d]) if d in hist["level_factors"] else 0.0
                cl.append(c * math.exp(-acc))
            closes[isin] = dict(zip(series["days"], cl))
        else:
            closes[isin] = dict(zip(series["days"], series["close"]))
        disc = disc_all.get(isin, {})
        feats[isin] = features.stock_feature_rows(series, hist["bad_days"], hist["return_factors"], hist["level_factors"])
        data[isin] = {"bars": {b.day: b for b in view.bars(isin)}, "factors": view.implied_factors(isin),
                      "unchecked": unchecked, "index": index, "disc": disc}
        if progress and n % 100 == 0:
            progress(f"features {n}/{len(isins)}")
    breadth = features.breadth_50({d: s.isins for d, s in universe.items()}, closes, sessions)
    mkt = features.market_feature_rows(index, breadth)
    nan_stock = {f: float("nan") for f in features.STOCK_FEATURES}
    nan_mkt = {f: float("nan") for f in features.MARKET_FEATURES}
    opps, counts, fmiss = [], {}, 0
    for d in decision_days:
        u = universe[d]
        if not u.isins:
            continue
        bars_today = {i: b for i, b in view.cross_section(d)}
        m = mkt.get(d) or nan_mkt
        for isin in u.isins:
            f = feats[isin].get(d)
            fx = dict(f or nan_stock, **m)
            for a in cfg.ablate:
                fx[a] = 0.0
            miss = [k for k in features.FEATURES if not features._finite(fx.get(k))]
            fmiss += bool(miss)
            lab = labels.forward_return(view, isin, d, cfg.h, sessions=sessions, panel_days=panel_days,
                                        index_name=cfg.index_name,
                                        listed_action_days=listed_actions(isin) if listed_actions else None, data=data[isin],
                                        actions=actions)
            key = lab.status if lab.status == labels.RESOLVED else f"{lab.status}:{lab.reason}"
            counts[key] = counts.get(key, 0) + 1
            b = bars_today[isin]
            opps.append({"day": d, "isin": isin, "symbol": b.symbol, "ref_close": b.close, "median_value": u.median_value[isin],
                         "features": fx, "missing": miss, "sigma": (f["vol_20"] * math.sqrt(cfg.h)) if f else float("nan"),
                         "label": lab})
    return Dataset(sessions, panel_days, missing, basis, universe, opps, counts, fmiss, view.content_hash(), view.end_limit,
                   lineage)


def folds(sessions: list[date], cfg: Config, holdout_start: date | None = None) -> list[dict]:
    """Chronological folds over session indices. Development: the sessions given end before the holdout start.
    Holdout: one fold whose test window is every session from the holdout start."""
    if cfg.evaluate_holdout:
        if holdout_start is None:
            raise ValueError("HOLDOUT_NOT_FROZEN")
        hs = next((i for i, d in enumerate(sessions) if d >= holdout_start), None)
        if hs is None:
            return []
        return [{"train_start": max(0, hs - cfg.train_sessions), "train_end": hs - 1, "test_start": hs,
                 "test_end": len(sessions) - 1}]
    n = len(sessions) if holdout_start is None else sum(1 for d in sessions if d < holdout_start)
    out = []
    test_start = cfg.train_sessions
    while test_start + cfg.test_sessions <= n:
        out.append({"train_start": test_start - cfg.train_sessions, "train_end": test_start - 1,
                    "test_start": test_start, "test_end": test_start + cfg.test_sessions - 1})
        test_start += cfg.step_sessions
    return out


def _icc_by_date(resid: dict[date, list[float]]) -> float:
    """One-way ANOVA intra-class correlation of residuals within dates, clipped to [0, 1)."""
    groups = [g for g in resid.values() if len(g) >= 2]
    if len(groups) < 2:
        return float("nan")
    N, G = sum(len(g) for g in groups), len(groups)
    grand = sum(sum(g) for g in groups) / N
    ssb = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb, msw = ssb / (G - 1), ssw / max(1, N - G)
    n0 = (N - sum(len(g) ** 2 for g in groups) / N) / (G - 1)
    den = msb + (n0 - 1) * msw
    return min(0.999, max(0.0, (msb - msw) / den)) if den > 0 else float("nan")


def fold_metrics(preds: list[dict], model: forecast.Model, train_y: list[float]) -> dict:
    """Calibration and discrimination on test forecasts whose labels resolved. Outcome: the gross excess log
    return > 0 (spec 4.5 probability_positive). References (base rate, unconditional quantiles) are fitted on the
    training labels, so they are deployable."""
    res = [p for p in preds if p["label"].status == labels.RESOLVED]
    out = {"outcome": "gross excess log return > 0", "n_predictions": len(preds), "n": len(res)}
    if not res:
        return out | {"coverage_80": float("nan"), "brier": float("nan"), "brier_skill": float("nan")}
    y = [p["label"].excess for p in res]
    pos = [1 if v > 0 else 0 for v in y]
    base = sum(1 for v in train_y if v > 0) / len(train_y) if train_y else float("nan")
    pr = [p["p_positive"] for p in res]
    brier = monitor.brier(pr, pos)
    ref = sum((base - yi) ** 2 for yi in pos) / len(pos)
    by_day, resid = {}, {}
    for p, v in zip(res, y):
        by_day.setdefault(p["day"], []).append((p["mu_hat"], v))
        resid.setdefault(p["day"], []).append(v - p["mu_hat"])
    ics = [spearman([a for a, _ in xs], [b for _, b in xs]) for xs in by_day.values() if len(xs) >= 5]
    ics = [v for v in ics if not math.isnan(v)]
    srt = sorted(train_y)
    pin = {f"pinball_{t}": sum(forecast.pinball(v, p[f"q{int(t * 100)}"], t) for p, v in zip(res, y)) / len(res)
           for t in (0.1, 0.5, 0.9)}
    pin_ref = {f"pinball_{t}_unconditional": sum(forecast.pinball(v, quantile(srt, t), t) for v in y) / len(y)
               for t in (0.1, 0.5, 0.9)} if srt else {}
    pits = [forecast.pit(model, p["mu_hat"], p["sigma_hat"], v) for p, v in zip(res, y)]
    return out | {"coverage_80": monitor.coverage([p["q10"] for p in res], [p["q90"] for p in res], y),
                  "brier": brier, "brier_reference_train_base_rate": base,
                  "brier_skill": 1 - brier / ref if ref > 0 else float("nan"),
                  "brier_skill_vs_test_base_rate_diagnostic": monitor.brier_skill(pr, pos),
                  "pit_ks": monitor.pit_ks(pits), "rank_ic_mean": sum(ics) / len(ics) if ics else float("nan"),
                  "rank_ic_days": len(ics), "residual_icc_by_date": _icc_by_date(resid),
                  "mean_y": sum(y) / len(y), "mean_mu": sum(p["mu_hat"] for p in res) / len(res), **pin, **pin_ref}


def run_fold(ds: Dataset, fold: dict, cfg: Config, trial_id: str, view: Panel, listed=None, actions=None) -> dict:
    s = ds.sessions
    ts, te = fold["test_start"], fold["test_end"]
    test_lo, test_hi = s[ts], s[te]
    embargo_day = s[max(0, ts - cfg.h)]
    complete = [o for o in ds.opportunities if not o["missing"] and s[fold["train_start"]] <= o["day"] <= test_hi]
    ranked = features.rank_stock_features(complete)
    train = [o for o in ranked if o["day"] <= s[fold["train_end"]] and o["label"].status == labels.RESOLVED
             and o["label"].exit_day < embargo_day]  # purge by actual outcome date + embargo
    test = [o for o in ranked if test_lo <= o["day"] <= test_hi]
    fold_dates = {k: s[v].isoformat() for k, v in fold.items()}
    if len({o["day"] for o in train}) < 50 or not test:
        return {"fold": fold_dates, "skipped": "INSUFFICIENT_ROWS", "n_train": len(train), "n_test": len(test)}
    ms = features.market_stats(train)
    train = [o for o in features.scale_market_features(train, ms) if not features.missing_features(o["x"])]
    test = features.scale_market_features(test, ms)
    ys = features.winsorize_targets([o["label"].excess for o in train])
    fit_rows = [{"day": o["day"], "isin": o["isin"], "x": o["x"], "y": y, "sigma": o["sigma"],
                 "y_abs": o["label"].gross_log, "idx": o["label"].index_log} for o, y in zip(train, ys)]
    model = forecast.fit(fit_rows, h=cfg.h, target_id=f"{cfg.candidate}.h{cfg.h}.v2", lam_grid=cfg.lam_grid, sessions=s,
                         bootstrap=cfg.bootstrap, seed=cfg.seed)
    preds, fcs = [], {}
    abstained = sum(1 for o in ds.opportunities if test_lo <= o["day"] <= test_hi and o["missing"])
    for o in test:
        if features.missing_features(o["x"]) or not (o["sigma"] > 0):
            abstained += 1
            continue
        p = forecast.predict(model, o["x"], o["sigma"])
        if "abstain" in p:
            return {"fold": fold_dates, "skipped": p["abstain"], "calibration_n": model.calibration_n}
        preds.append(dict(p, day=o["day"], isin=o["isin"], label=o["label"]))
        z = model.z_sorted
        fcs.setdefault(o["day"], {})[o["isin"]] = dict(
            p, ref_close=o["ref_close"], symbol=o["symbol"], median_value=o["median_value"],
            _p_above=lambda c, mu=p["mu_hat"], sg=p["sigma_hat"], z=z: forecast.conformal_probability_above(z, (c - mu) / sg))
    metrics = fold_metrics(preds, model, [o["label"].excess for o in train]) | {"abstained_feature_coverage": abstained}
    policy = cfg.effective_policy()
    excl = {d: ds.universe[d].excluded for d in ds.universe if test_lo <= d <= test_hi}
    sim_kw = dict(policy=policy, h=cfg.h, index_name=cfg.index_name, exclusions=excl, listed=listed, actions=actions)
    sim = replay.simulate(view, s, ds.panel_days, ts, te, fcs, execution=cfg.execution, **sim_kw)
    stresses = {}
    for name, ex in (("costs_x2", replace(cfg.execution, charge_multiplier=2.0)),
                     ("slippage_x2", replace(cfg.execution, slippage_multiplier=2.0)),
                     ("entry_one_session_late", replace(cfg.execution, entry_delay_sessions=cfg.execution.entry_delay_sessions + 1))):
        stresses[name] = replay.simulate(view, s, ds.panel_days, ts, te, fcs, execution=ex, **sim_kw)["net_rupees"]
    nets = sorted((t["net_rupees"] for t in sim["trades"]), reverse=True)
    cut = math.ceil(0.05 * len(nets)) if nets else 0
    stresses["best_5pct_trades_removed"] = round(sim["net_rupees"] - sum(nets[:cut]), 2)
    test_days = [d for d in s[ts:te + 1]]
    unverified_days = sum(1 for d in test_days if d in ds.universe and ds.universe[d].unverified)
    flagged = [t for t in sim["trades"] if t["action_status"] != "NONE"] + \
              [o for o in sim["open_positions"] if o["action_status"] != "NONE"]
    evidence = {"sessions_from_calendar": all(ds.session_basis.get(d.year) == "CALENDAR" for d in test_days),
                "missing_sessions_in_test": sum(1 for d in test_days if d not in ds.panel_days),
                "eligibility_unverified_days": unverified_days,
                "availability": sorted({ds.universe[d].availability for d in test_days if d in ds.universe}),
                "action_unverified_positions": len(flagged)}
    evidence["verified"] = (evidence["sessions_from_calendar"] and unverified_days == 0 and not flagged
                            and evidence["missing_sessions_in_test"] == 0)
    return {"fold": fold_dates, "trial_id": trial_id, "model": model.to_json(), "n_train": len(train),
            "n_test": len(test), "metrics": metrics, "simulation": {k: v for k, v in sim.items() if k != "events"},
            "events_sample": sim["events"][:200], "stresses": stresses, "evidence": evidence}


def jsonable(x):
    """NaN/inf -> None (undefined stays undefined), Decimal/date -> str, dataclasses -> dict, callables dropped."""
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items() if not callable(v) and not str(k).startswith("_")}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v) for v in x]
    if isinstance(x, (Decimal, date)):
        return str(x) if isinstance(x, Decimal) else x.isoformat()
    if hasattr(x, "__dataclass_fields__"):
        return jsonable({f: getattr(x, f) for f in x.__dataclass_fields__})
    return x


# ---- evidence for the promotion rule ------------------------------------------------------------------------

def _trade_stats(trades: list[dict]) -> dict:
    rets = [t["net_return"] for t in trades]
    if len(rets) < 3:
        return {"n": len(rets)}
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    out = {"n": len(rets), "mean_net_return": m, "sd": sd, "sharpe_per_trade": m / sd if sd > 0 else float("nan")}
    try:
        out["skew"], out["kurtosis"] = moments(rets)
    except (MetricUnavailable, ValueError, ZeroDivisionError):
        out["skew"], out["kurtosis"] = 0.0, 3.0
    return out


def _daily_returns(done: list[dict]) -> dict[str, float]:
    """Daily NAV returns across folds (each fold starts at the policy capital)."""
    out = {}
    for r in done:
        prev = r["simulation"]["policy"]["W"]
        for row in r["simulation"]["nav"]:
            out[row["day"]] = row["nav"] / prev - 1 if prev else 0.0
            prev = row["nav"]
    return out


def attribution(done: list[dict], view: Panel, index_name: str) -> dict | None:
    """Beta and alpha of daily NAV returns on the benchmark's close-to-close returns (cash days included), plus
    the average invested fraction. None when fewer than 20 aligned days exist."""
    rets = _daily_returns(done)
    if not rets:
        return None
    days = sorted(rets)
    idx = view.index_levels(index_name, date.fromisoformat(days[0]) - timedelta(days=10), date.fromisoformat(days[-1]))
    closes = sorted((d, c) for d, (_, c) in idx.items() if c)
    mret = {closes[i][0].isoformat(): closes[i][1] / closes[i - 1][1] - 1 for i in range(1, len(closes))}
    pairs = [(rets[d], mret[d]) for d in days if d in mret]
    if len(pairs) < 20:
        return None
    mp, mm = sum(p for p, _ in pairs) / len(pairs), sum(m for _, m in pairs) / len(pairs)
    var = sum((m - mm) ** 2 for _, m in pairs) / (len(pairs) - 1)
    cov = sum((p - mp) * (m - mm) for p, m in pairs) / (len(pairs) - 1)
    beta = cov / var if var > 0 else float("nan")
    navs = [row for r in done for row in r["simulation"]["nav"]]
    invested = sum(row["positions"] / row["nav"] for row in navs if row["nav"]) / len(navs) if navs else float("nan")
    return {"days": len(pairs), "beta": beta, "alpha_daily": mp - beta * mm if not math.isnan(beta) else float("nan"),
            "mean_invested_fraction": invested, "benchmark": index_name + " price index, close to close"}


def concentration(done: list[dict]) -> dict:
    by_stock, by_year = {}, {}
    for r in done:
        sim = r["simulation"]
        for t in sim["trades"]:
            by_stock[t["isin"]] = by_stock.get(t["isin"], 0.0) + t["net_rupees"]
            y = t["exit_day"][:4]
            by_year[y] = by_year.get(y, 0.0) + t["net_rupees"]
        end_year = r["fold"]["test_end"][:4]
        for o in sim["open_positions"]:
            by_stock[o["isin"]] = by_stock.get(o["isin"], 0.0) + o["unrealized_net"]
            by_year[end_year] = by_year.get(end_year, 0.0) + o["unrealized_net"]
    total = sum(by_stock.values())
    share = (lambda d: max(d.values()) / total if d and total > 0 else float("nan"))
    return {"total": round(total, 2), "max_stock_share": share(by_stock), "max_year_share": share(by_year),
            "by_year": {k: round(v, 2) for k, v in sorted(by_year.items())}}


def n_effective(done: list[dict], h: int) -> dict:
    """N_eff = sum over h-session entry blocks of m_b / (1 + (m_b - 1) rho), rho the pooled within-date residual
    correlation of the test forecasts (spec 8.4)."""
    rhos = [(r["metrics"].get("residual_icc_by_date"), r["metrics"].get("n", 0)) for r in done]
    rhos = [(v, n) for v, n in rhos if v is not None and not math.isnan(v) and n]
    rho = sum(v * n for v, n in rhos) / sum(n for _, n in rhos) if rhos else float("nan")
    blocks = {}
    for r in done:
        days = [row["day"] for row in r["simulation"]["nav"]]
        pos = {d: i for i, d in enumerate(days)}
        for t in r["simulation"]["trades"]:
            b = (r["fold"]["test_start"], pos.get(t["entry_day"], 0) // max(1, h))
            blocks[b] = blocks.get(b, 0) + 1
    if math.isnan(rho):
        return {"rho": rho, "n_eff": float("nan"), "blocks": len(blocks)}
    return {"rho": rho, "n_eff": monitor.effective_n([(m, rho) for m in blocks.values()]), "blocks": len(blocks)}


def pbo(reports: list[dict], n_blocks: int = 16) -> dict:
    """CSCV over aligned daily NAV returns of every registered trial (metric: mean daily return, which stays
    defined for trials that never trade); rows are trimmed from the start to split into equal blocks."""
    series = {r["trial_id"]: r.get("daily_returns") or {} for r in reports}
    series = {k: v for k, v in series.items() if v}
    if len(series) < 2:
        return {"pbo": None, "reason": "FEWER_THAN_2_TRIALS", "trials": len(series)}
    days = sorted(set.intersection(*(set(v) for v in series.values())))
    drop = len(days) % n_blocks
    days = days[drop:]
    if len(days) < 2 * n_blocks:
        return {"pbo": None, "reason": "TOO_FEW_ALIGNED_DAYS", "trials": len(series), "days": len(days)}
    names = sorted(series)
    mat = [[series[n][d] for n in names] for d in days]
    try:
        res = probability_of_backtest_overfitting(mat, n_blocks, metric=lambda xs: sum(xs) / len(xs))
    except MetricUnavailable as e:
        return {"pbo": None, "reason": str(e), "trials": len(names)}
    return {"pbo": res.pbo, "splits": res.n_splits, "trials": len(names), "days": len(days), "rows_dropped": drop}


def _num(x) -> float:
    return float("nan") if x is None else float(x)


def promotion(report: dict, *, registry_reports: list[dict], holdout_report: dict | None) -> dict:
    """Spec 8.6 with every criterion evaluated; a criterion without evidence is None. Verdict: PROMOTED when all
    are True; INSUFFICIENT EVIDENCE when N_eff < MinTRL or any criterion lacks evidence (None); otherwise REJECT.
    Only folds whose evidence is verified (calendar sessions, verified eligibility, no data gaps, no unverified
    corporate action) count."""
    done = [r for r in report.get("folds", []) if "skipped" not in r]
    ver = [r for r in done if r["evidence"]["verified"]]
    crit: dict[str, bool | None] = {}
    crit["verified_folds_exist"] = True if ver else None  # unverified folds are reported, never counted
    nets = [r["simulation"]["net_rupees"] for r in ver]
    crit["net_positive_pooled"] = (sum(nets) > 0) if nets else None
    crit["folds_positive_60pct"] = (sum(1 for v in nets if v > 0) / len(nets) >= 0.6) if nets else None
    trades = [t for r in ver for t in r["simulation"]["trades"]]
    st = _trade_stats(trades)
    ne = n_effective(ver, report.get("config", {}).get("h", 20)) if ver else {"n_eff": float("nan")}
    sr = _num(st.get("sharpe_per_trade"))
    mtrl = None
    if not math.isnan(sr) and sr != 0:
        try:  # SR > 0: track record needed to establish SR > 0; SR < 0: needed to establish the loss (symmetric)
            mtrl = (min_track_record_length(sr, 0.0, st["skew"], st["kurtosis"]) if sr > 0
                    else min_track_record_length(0.0, sr, st["skew"], st["kurtosis"]))
        except MetricUnavailable:
            mtrl = None
    n_eff = _num(ne.get("n_eff"))
    crit["n_eff_ge_mintrl"] = None if (mtrl is None or math.isnan(n_eff)) else n_eff >= mtrl
    sharpes = [_num((r.get("pooled") or {}).get("sharpe_per_trade")) for r in registry_reports]
    sharpes = [v for v in sharpes if not math.isnan(v)]
    n_trials = len({r.get("trial_id") for r in registry_reports if r.get("trial_id")})
    dsr = None
    if not math.isnan(sr) and n_trials >= 2 and len(sharpes) >= 2 and not math.isnan(n_eff) and n_eff >= 2:
        mean_s = sum(sharpes) / len(sharpes)
        var_s = sum((v - mean_s) ** 2 for v in sharpes) / (len(sharpes) - 1)
        try:
            dsr = deflated_sharpe_ratio(sr, int(n_eff), st["skew"], st["kurtosis"], n_trials=n_trials,
                                        sr_variance_across_trials=var_s)
        except MetricUnavailable:
            dsr = None
    crit["dsr_95"] = None if dsr is None else dsr >= 0.95
    pb = pbo(registry_reports)
    crit["pbo_le_025"] = None if pb.get("pbo") is None else pb["pbo"] <= 0.25
    covs = [(_num(r["metrics"].get("coverage_80")), r["metrics"].get("n", 0)) for r in ver]
    covs = [(v, n) for v, n in covs if n and not math.isnan(v)]
    res_n = sum(n for _, n in covs)
    cov = sum(v * n for v, n in covs) / res_n if res_n else float("nan")
    bss = [(_num(r["metrics"].get("brier_skill")), r["metrics"].get("n", 0)) for r in ver]
    bss = [(v, n) for v, n in bss if n and not math.isnan(v)]
    bss_v = sum(v * n for v, n in bss) / sum(n for _, n in bss) if bss else float("nan")
    conclusive = res_n >= MIN_COVERAGE_N
    crit["coverage_80_in_band"] = (0.72 <= cov <= 0.88) if conclusive and not math.isnan(cov) else None
    crit["brier_skill_positive"] = (bss_v > 0) if conclusive and not math.isnan(bss_v) else None
    if trades:
        totals = {k: sum((r.get("stresses") or {}).get(k, 0.0) for r in ver) for k in
                  ("costs_x2", "slippage_x2", "entry_one_session_late", "best_5pct_trades_removed")}
        crit["stresses_net_positive"] = all(v > 0 for v in totals.values())
    else:
        totals, crit["stresses_net_positive"] = {}, None
    conc = concentration(ver) if ver else {}
    if conc and conc["total"] > 0 and not math.isnan(_num(conc["max_stock_share"])):
        crit["no_year_or_stock_over_half"] = conc["max_stock_share"] <= 0.5 and conc["max_year_share"] <= 0.5
    elif conc and trades and conc["total"] <= 0:
        crit["no_year_or_stock_over_half"] = False  # no positive net to be spread: the criterion cannot hold
    else:
        crit["no_year_or_stock_over_half"] = None
    crit["attribution_available"] = True if report.get("attribution") else None
    hold = holdout_report
    crit["holdout_net_positive"] = None if hold is None else (hold.get("net_rupees_total") or 0) > 0
    if all(v is True for v in crit.values()):
        verdict = "PROMOTED"
    elif crit["n_eff_ge_mintrl"] is False or any(v is None for v in crit.values()):
        verdict = "INSUFFICIENT EVIDENCE"
    else:
        verdict = "REJECT"
    return {"verdict": verdict, "criteria": crit, "dsr": dsr, "n_trials_registered": n_trials, "pbo": pb,
            "min_track_record": mtrl, "n_eff": ne, "trade_stats": st, "coverage_80_pooled": cov,
            "brier_skill_pooled": bss_v, "resolved_test_forecasts": res_n, "stresses_pooled": totals,
            "concentration": conc, "verified_folds": len(ver), "folds_done": len(done)}


# ---- the run ---------------------------------------------------------------------------------------------------

def summarize(results: list[dict], cfg: Config, ds: Dataset, trial_id: str) -> dict:
    done = [r for r in results if "skipped" not in r]
    net_by_fold = [r["simulation"]["net_rupees"] for r in done]
    trades = [t for r in done for t in r["simulation"]["trades"]]
    st = _trade_stats(trades)
    if st.get("sharpe_per_trade") is not None and not math.isnan(st.get("sharpe_per_trade", float("nan"))):
        try:
            st["psr_vs_zero"] = probabilistic_sharpe_ratio(st["sharpe_per_trade"], 0.0, st["n"], st["skew"], st["kurtosis"])
        except MetricUnavailable as e:
            st["psr_error"] = str(e)
    return {"trial_id": trial_id, "generated_at": now().isoformat(), "holdout": cfg.evaluate_holdout,
            "config": {f.name: (list(getattr(cfg, f.name)) if isinstance(getattr(cfg, f.name), tuple) else getattr(cfg, f.name))
                       for f in fields(cfg) if f.name not in ("screen", "policy", "execution")},
            "screen": jsonable(cfg.screen), "manifest_hash": ds.manifest_hash,
            "data_end": ds.end.isoformat() if ds.end else None,
            "sessions": [ds.sessions[0].isoformat(), ds.sessions[-1].isoformat()] if ds.sessions else [],
            "session_basis": {str(k): v for k, v in sorted(ds.session_basis.items())},
            "missing_sessions": {"count": len(ds.missing_sessions), "first": [d.isoformat() for d in ds.missing_sessions[:20]]},
            "opportunities": len(ds.opportunities), "feature_missing": ds.feature_missing, "rows": len(ds.rows),
            "label_counts": ds.label_counts,
            "eligibility_unverified_days": sum(1 for u in ds.universe.values() if u.unverified),
            "folds": results, "net_rupees_by_fold": net_by_fold, "net_rupees_total": round(sum(net_by_fold), 2),
            "folds_positive": sum(1 for v in net_by_fold if v > 0), "folds_done": len(done), "n_trades": len(trades),
            "pooled": st, "daily_returns": _daily_returns(done),
            "profitability_proven": False,
            "note": "Research diagnostic from a causal replay ledger. Net rupees include open positions at liquidation "
                    "value. Promotion requires every spec 8.6 criterion (see 'promotion')."}


def walk_forward(panel: Panel, cfg: Config, *, runs: Path, calendar, rule_inputs_fn=None, listed_actions=None, actions=None,
                 progress=print) -> dict:
    """One registered trial. Development: folds over the panel view ending the day before the frozen holdout.
    Holdout (cfg.evaluate_holdout): once per trial, after everything else is final."""
    spec = candidates.require(cfg.candidate, cfg.h, cfg.ablate)  # B/C and unregistered trials stop here
    man = registry.holdout_manifest(runs)
    if man is None:
        raise ValueError("HOLDOUT_NOT_FROZEN: freeze the holdout once after the backfill (marketlab freeze-holdout)")
    hs = date.fromisoformat(man["holdout_start"])
    trial_id = cfg.trial_id()
    if cfg.evaluate_holdout and registry.holdout_runs(runs, trial_id):
        raise ValueError("HOLDOUT_ALREADY_EVALUATED: the holdout of this trial was opened before")
    view = panel.view(None if cfg.evaluate_holdout else hs - timedelta(days=1))
    ds = build_dataset(view, cfg, calendar=calendar, rule_inputs_fn=rule_inputs_fn, listed_actions=listed_actions, actions=actions,
                       progress=progress)
    listed = (lambda isin, d: d in (listed_actions(isin) or set())) if listed_actions else None
    results = [run_fold(ds, f, cfg, trial_id, view, listed, actions) for f in folds(ds.sessions, cfg, hs)]
    report = summarize(results, cfg, ds, trial_id)
    report.update(candidate_spec=candidates.describe(spec, cfg.ablate), policy=cfg.effective_policy().to_json(),
                  policy_digest=cfg.effective_policy().digest(), execution=cfg.execution.to_json(),
                  holdout_start=man["holdout_start"], run_id=registry.run_id(trial_id, ds.manifest_hash),
                  attribution=attribution([r for r in results if "skipped" not in r], view, cfg.index_name))
    report = jsonable(report)
    if not cfg.evaluate_holdout:
        others = [r for r in registry.development_reports(runs) if r.get("trial_id") != trial_id]
        report["promotion"] = jsonable(promotion(report, registry_reports=others + [report], holdout_report=None))
    else:
        report["development_run_id"] = (next((r for r in registry.development_reports(runs) if r.get("trial_id") == trial_id), {})
                                        .get("run_id"))
    path = registry.write_run(runs, report)
    report["path"] = str(path)
    return report
