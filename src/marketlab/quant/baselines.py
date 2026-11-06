"""Does the model's ranking beat simple strategies under identical conditions? (owner's test design, stage 3)

Inside each walk-forward fold, on non-overlapping holding periods (decision every h sessions from the test start),
four strategies pick from the SAME dated, eligible universe and are measured the SAME way:

  model     the K stocks with the highest shrunk forecast mu~ (the model's own order, without its gates or allocator,
            so this measures ranking skill alone; the full strategy is the replay ledger's result)
  momentum  the K stocks with the highest raw 12-1 momentum (the best-known simple equity signal)
  random    K stocks drawn at random, repeated ``draws`` times with a fixed seed (the null: no skill)
  nifty     the Nifty 50 itself over the same entry and exit opens (a price index: dividends excluded on both sides)

Execution matches the labels and EXEC.v1: entry at the next session's open, exit at the open h sessions later,
whole shares of an equal slice of the invested capital, exact Zerodha delivery charges and the DP fee, and the
liquidity-tier slippage on both sides. Picks whose label is not RESOLVED (an unexplained price adjustment, no exit
price) are counted per strategy, never silently dropped from the denominator of the comparison.

Returns are on capital: (sum of net rupees) / W, with the same invested fraction (1 - reserve) for every strategy,
the Nifty included. Comparisons use a moving-block bootstrap over periods and, for the random null, the share of
random portfolios that did at least as well.
"""
from __future__ import annotations

import math
import random
import statistics

from . import allocate, labels

STRATEGIES = ("model", "momentum", "random", "nifty")


def _net(label, decision_price: float, value_target: float, slippage_side: float) -> dict | None:
    """Net result of one whole-share position held over the label's window, or None when it cannot be scored.
    The quantity is fixed at decision time from the decision close (as EXEC.v1 freezes intents); the fill is the
    next open, which is not known when the stock is chosen."""
    entry = label.entry_open
    if not (entry and entry > 0) or label.status != labels.RESOLVED or not decision_price > 0:
        return None
    q = int(value_target // decision_price)
    if q <= 0:
        return None
    c = allocate.Candidate("", entry, 0.0, 0.0, 2 * slippage_side)
    pc = allocate.position_costs(c, q)
    gross_rupees = q * entry * label.gross
    costs = pc["charges"] + pc["slippage"]
    return {"invested": q * entry, "gross": gross_rupees, "costs": costs, "net": gross_rupees - costs}


def _pick(ordered: list[dict], k: int, value_target: float) -> list[dict]:
    """The first k affordable names of an ordered list, judged at the decision close (a stock whose one share
    exceeds the slice is skipped; the next open is not known when choosing)."""
    out = []
    for r in ordered:
        if len(out) >= k:
            break
        if r.get("ref_close") and r["ref_close"] <= value_target:
            out.append(r)
    return out


def _period(picks: list[dict], value_target: float, W: float) -> dict:
    res = [_net(r["label"], r["ref_close"], value_target, labels.slippage_for(r.get("median_value") or 0.0)) for r in picks]
    unresolved = sum(1 for x in res if x is None)
    done = [x for x in res if x is not None]
    net = sum(x["net"] for x in done)
    return {"ret": net / W, "net": net, "costs": sum(x["costs"] for x in done), "invested": sum(x["invested"] for x in done),
            "trades": [x["net"] / x["invested"] for x in done], "unresolved": unresolved, "n": len(picks)}


def fold_periods(rows: list[dict], sessions: list, ts: int, te: int, h: int, policy: allocate.Policy, *,
                 draws: int = 200, seed: int = 0) -> dict:
    """rows: one per (decision day, eligible stock) in the fold's test window with day, isin, mu, mom, label,
    median_value and ref_close (the decision close: every choice uses decision-time information only). Returns per-strategy period results (random: each draw's mean and per-period values)."""
    k = max(1, policy.K)
    invest = policy.W * (1 - policy.reserve_fraction)
    slice_ = min(policy.cap_fraction * policy.W, invest / k)
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    rng = random.Random(seed)
    out = {"model": [], "momentum": [], "nifty": [], "random_draws": [[] for _ in range(draws)], "days": []}
    for i in range(ts, te + 1, h):
        d = sessions[i]
        day_rows = [r for r in by_day.get(d, []) if r["label"] is not None]
        if len(day_rows) < k:
            continue
        resolved_idx = [r["label"].index_log for r in day_rows
                        if r["label"].status == labels.RESOLVED and r["label"].index_log is not None]
        if not resolved_idx:
            continue  # the holding window has not resolved yet for anyone: nothing can be scored
        out["days"].append(d.isoformat() if hasattr(d, "isoformat") else str(d))
        out["model"].append(_period(_pick(sorted(day_rows, key=lambda r: -r["mu"]), k, slice_), slice_, policy.W))
        mom = [r for r in day_rows if r.get("mom") is not None]
        out["momentum"].append(_period(_pick(sorted(mom, key=lambda r: -r["mom"]), k, slice_), slice_, policy.W))
        idx_simple = math.exp(statistics.median(resolved_idx)) - 1
        out["nifty"].append({"ret": (1 - policy.reserve_fraction) * idx_simple, "net": invest * idx_simple, "costs": 0.0,
                             "invested": invest, "trades": [idx_simple], "unresolved": 0, "n": 1})
        for j in range(draws):
            sample = day_rows[:]
            rng.shuffle(sample)
            out["random_draws"][j].append(_period(_pick(sample, k, slice_), slice_, policy.W)["ret"])
    return out


def _max_drawdown(rets: list[float]) -> float:
    nav, peak, worst = 1.0, 1.0, 0.0
    for r in rets:
        nav *= 1 + r
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1)
    return worst


def metrics(periods: list[dict], h: int) -> dict:
    """Owner's stage-3 table for one strategy over its periods (returns on capital per holding period)."""
    rets = [p["ret"] for p in periods]
    trades = [t for p in periods for t in p["trades"]]
    if not rets:
        return {"periods": 0}
    m = statistics.fmean(rets)
    sd = statistics.stdev(rets) if len(rets) > 1 else float("nan")
    down = [min(0.0, r) for r in rets]
    dsd = math.sqrt(sum(x * x for x in down) / len(down)) if down else float("nan")
    ann = math.sqrt(252 / h)
    gains, losses = sum(t for t in trades if t > 0), -sum(t for t in trades if t < 0)
    nav = 1.0
    for r in rets:
        nav *= 1 + r
    return {"periods": len(rets), "mean_period_return": m, "median_period_return": statistics.median(rets),
            "period_win_rate": sum(r > 0 for r in rets) / len(rets),
            "trades": len(trades), "trade_win_rate": (sum(t > 0 for t in trades) / len(trades)) if trades else None,
            "mean_trade_return": statistics.fmean(trades) if trades else None,
            "median_trade_return": statistics.median(trades) if trades else None,
            "net_rupees": sum(p["net"] for p in periods), "costs_rupees": sum(p["costs"] for p in periods),
            "compounded_return": nav - 1, "max_drawdown": _max_drawdown(rets),
            "sharpe_annualized": m / sd * ann if sd and sd > 0 else None,
            "sortino_annualized": m / dsd * ann if dsd and dsd > 0 else None,
            "profit_factor": gains / losses if losses > 0 else None,
            "turnover_per_period": 1.0,  # every position is replaced each holding period by construction
            "unresolved_picks": sum(p["unresolved"] for p in periods), "picks": sum(p["n"] for p in periods)}


def block_bootstrap_ci(diffs: list[float], *, block: int = 3, reps: int = 2000, seed: int = 0) -> dict:
    """95% interval of the mean of per-period differences by a moving-block bootstrap (consecutive periods share
    market regimes; blocks keep that dependence)."""
    n = len(diffs)
    if n < 4:
        return {"n": n, "mean": statistics.fmean(diffs) if diffs else None, "ci95": None}
    rng = random.Random(seed)
    b = max(1, min(block, n))
    starts = list(range(n - b + 1))
    means = []
    for _ in range(reps):
        s = []
        while len(s) < n:
            st = rng.choice(starts)
            s.extend(diffs[st:st + b])
        means.append(statistics.fmean(s[:n]))
    means.sort()
    return {"n": n, "mean": statistics.fmean(diffs), "ci95": [means[int(0.025 * reps)], means[int(0.975 * reps) - 1]],
            "share_above_zero": sum(x > 0 for x in means) / reps}


def compare(all_periods: dict, h: int) -> dict:
    """Pooled over folds: each strategy's metrics, the model against each simple strategy (block-bootstrap CI on the
    per-period difference), and where the model sits among the random portfolios."""
    out = {"strategies": {s: metrics(all_periods[s], h) for s in ("model", "momentum", "nifty")}}
    draws = all_periods["random_draws"]
    draw_means = sorted(statistics.fmean(d) for d in draws if d)
    out["strategies"]["random"] = {"draws": len(draw_means), "median_of_draw_means": statistics.median(draw_means)
                                   if draw_means else None, "p05_p95": [draw_means[int(0.05 * len(draw_means))],
                                                                        draw_means[int(0.95 * len(draw_means)) - 1]]
                                   if len(draw_means) >= 20 else None}
    model_r = [p["ret"] for p in all_periods["model"]]
    for other in ("momentum", "nifty"):
        other_r = [p["ret"] for p in all_periods[other]]
        out[f"model_minus_{other}"] = block_bootstrap_ci([a - b for a, b in zip(model_r, other_r)])
    if model_r and draw_means:
        mm = statistics.fmean(model_r)
        out["model_vs_random"] = {"model_mean": mm, "share_of_random_at_least_as_good": sum(x >= mm for x in draw_means)
                                  / len(draw_means)}
    out["note"] = ("Ranking skill only: top-K by each score, equal slices, same entry/exit opens and costs. A price "
                   "index benchmark (no dividends) matches the price-return labels; a total-return comparison needs "
                   "dividend-adjusted labels (H-CA1). Folds share one trial; these numbers are not a second, "
                   "independent test of the strategy.")
    return out


def merge(fold_results: list[dict]) -> dict:
    """Concatenate the per-fold periods of every strategy, aligning random draws by index."""
    merged = {"model": [], "momentum": [], "nifty": [], "random_draws": None, "days": []}
    for r in fold_results:
        b = r.get("baselines_periods")
        if not b:
            continue
        for s in ("model", "momentum", "nifty", "days"):
            merged[s].extend(b[s])
        if merged["random_draws"] is None:
            merged["random_draws"] = [list(d) for d in b["random_draws"]]
        else:
            for j, d in enumerate(b["random_draws"]):
                merged["random_draws"][j].extend(d)
    merged["random_draws"] = merged["random_draws"] or []
    return merged
