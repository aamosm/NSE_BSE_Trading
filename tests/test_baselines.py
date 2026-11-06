"""The simple-strategy comparison must reward real skill, refuse to invent it, and account for every pick."""
import math
import random
from datetime import date, timedelta

from marketlab.quant import allocate, baselines, labels


def _label(day, ret, idx=0.0, status=labels.RESOLVED, entry=100.0):
    return labels.Label("I", day, day, day, 20, status, None, entry_open=entry, exit_open=entry * (1 + ret), factor=1.0,
                        gross=ret, gross_log=math.log1p(ret), index_log=idx, excess=math.log1p(ret) - idx)


def _world(skill: bool, n_days=200, n_stocks=60, seed=1):
    rng = random.Random(seed)
    sessions = [date(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    rows = []
    for i in range(0, n_days, 20):
        d = sessions[i]
        idx = rng.gauss(0.01, 0.04)
        for j in range(n_stocks):
            mu = rng.gauss(0, 0.02)
            ret = (2.0 * mu if skill else 0.0) + rng.gauss(0, 0.05) + idx
            rows.append({"day": d, "isin": f"S{j}", "mu": mu, "mom": rng.gauss(0, 1), "median_value": 2e8,
                         "ref_close": 100.0, "label": _label(d, ret, idx=math.log1p(idx))})
    return sessions, rows


POL = allocate.Policy(100_000.0, K=5, cap_fraction=0.2, reserve_fraction=0.2)


def test_a_model_with_real_skill_beats_random_and_momentum_with_an_interval_above_zero():
    s, rows = _world(skill=True)
    per = baselines.fold_periods(rows, s, 0, len(s) - 1, 20, POL, draws=200)
    cmp = baselines.compare(per, 20)
    assert cmp["model_minus_momentum"]["ci95"][0] > 0
    assert cmp["model_vs_random"]["share_of_random_at_least_as_good"] < 0.05
    assert cmp["strategies"]["model"]["mean_period_return"] > cmp["strategies"]["random"]["median_of_draw_means"]


def test_a_model_without_skill_is_not_credited_with_any():
    s, rows = _world(skill=False)
    cmp = baselines.compare(baselines.fold_periods(rows, s, 0, len(s) - 1, 20, POL, draws=200), 20)
    lo, hi = cmp["model_minus_momentum"]["ci95"]
    assert lo < 0 < hi  # indistinguishable from a coin-flip ranking
    assert 0.05 < cmp["model_vs_random"]["share_of_random_at_least_as_good"] < 0.95


def test_costs_are_charged_and_the_index_is_held_with_the_same_invested_fraction():
    s, rows = _world(skill=True, n_days=20)
    per = baselines.fold_periods(rows, s, 0, 19, 20, POL, draws=5)
    m = per["model"][0]
    assert m["costs"] > 0 and m["net"] < sum(r["label"].gross for r in rows) * 1e9  # charges and slippage were taken
    idx = rows[0]["label"].index_log
    assert per["nifty"][0]["ret"] == (1 - POL.reserve_fraction) * (math.exp(idx) - 1)


def test_an_unaffordable_top_pick_is_skipped_and_unresolved_picks_are_counted():
    d = date(2020, 1, 1)
    rows = [{"day": d, "isin": "BIG", "mu": 0.09, "mom": 0, "median_value": 2e8, "ref_close": 50_000.0, "label": _label(d, 0.1, entry=50_000.0)},
            {"day": d, "isin": "GONE", "mu": 0.08, "mom": 0, "median_value": 2e8, "ref_close": 100.0,
             "label": _label(d, -0.5, status=labels.EXCLUDED)}]
    rows += [{"day": d, "isin": f"S{j}", "mu": 0.01 - j * 1e-3, "mom": 0, "median_value": 2e8, "ref_close": 100.0,
              "label": _label(d, 0.02)}
             for j in range(6)]
    per = baselines.fold_periods(rows, [d], 0, 0, 20, POL, draws=3)
    picked = per["model"][0]
    assert picked["n"] == 5 and picked["unresolved"] == 1  # BIG skipped (one share > the 16,000 slice); GONE counted
    assert len(picked["trades"]) == 4


def test_strategy_metrics_report_drawdown_and_downside_risk():
    m = baselines.metrics([{"ret": r, "net": r * 1e5, "costs": 10.0, "invested": 8e4, "trades": [r], "unresolved": 0, "n": 1}
                           for r in (0.05, -0.10, 0.02, -0.04, 0.03)], 20)
    assert m["max_drawdown"] < -0.10 and m["sortino_annualized"] is not None and m["profit_factor"] < 1.0
    assert m["period_win_rate"] == 0.6 and m["costs_rupees"] == 50.0


def test_choices_use_the_decision_close_not_the_next_open():
    """Look-ahead guard: a stock that gaps above the slice overnight was still affordable at the decision close, and
    its quantity is fixed from that close; the next open only sets the fill."""
    d = date(2020, 1, 1)
    gap = {"day": d, "isin": "GAP", "mu": 0.05, "mom": 0, "median_value": 2e8, "ref_close": 15_000.0,
           "label": _label(d, 0.0, entry=17_000.0)}  # one share: 15,000 at the close (fits 16,000), 17,000 at the open
    rest = [{"day": d, "isin": f"S{j}", "mu": 0.0, "mom": 0, "median_value": 2e8, "ref_close": 100.0,
             "label": _label(d, 0.0)} for j in range(6)]
    per = baselines.fold_periods([gap] + rest, [d], 0, 0, 20, POL, draws=2)
    m = per["model"][0]
    assert m["n"] == 5 and abs(m["invested"] - (17_000.0 + 4 * 160 * 100.0)) < 1e-6  # q = 1 from the close
