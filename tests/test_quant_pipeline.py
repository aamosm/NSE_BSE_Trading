"""Panel, labels, features, universe and the purged walk-forward on a synthetic panel (mechanics, not evidence)."""
import math
import random
from datetime import date, timedelta

import pytest

from marketlab.quant import evaluate, features, labels, registry
from marketlab.quant.panel import Panel
from marketlab.quant.universe import ScreenPolicy, screen
from synthetic import WeekdayCalendar

START = date(2020, 1, 1)
CAL = WeekdayCalendar()


def sessions(n):
    out, d = [], START
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def row(isin, sym, o, h, l, c, pc, vol, val, series="EQ", name="X LIMITED"):
    return {"ISIN": isin, "TckrSymb": sym, "SctySrs": series, "FinInstrmNm": name, "OpnPric": o, "HghPric": h, "LwPric": l,
            "ClsPric": c, "PrvsClsgPric": pc, "TtlTradgVol": vol, "TtlTrfVal": val, "TtlNbOfTxsExctd": 10}


@pytest.fixture
def panel(tmp_path):
    """30 stocks, 900 sessions, geometric random walk plus a planted cross-sectional momentum effect; one 1:1 bonus."""
    p = Panel(tmp_path / "panel.sqlite3")
    days = sessions(900)
    rng = random.Random(7)
    n = 30
    price = [100.0 * (1 + i / 10) for i in range(n)]
    drift = [0.0] * n
    bonus_day = days[600]
    idx_level = 10000.0
    for t, d in enumerate(days):
        rows = []
        mkt = rng.gauss(0, 0.008)
        for i in range(n):
            drift[i] = 0.9 * drift[i] + rng.gauss(0, 0.0005)  # slowly varying stock drift: momentum is informative
            r = mkt + drift[i] + rng.gauss(0, 0.015)
            pc = price[i]
            if d == bonus_day and i == 0:
                pc = price[i] / 2  # 1:1 bonus: exchange base price halves
                price[i] = price[i] / 2
            c = price[i] * math.exp(r)
            o = pc * math.exp(rng.gauss(0, 0.003))
            h, l = max(o, c) * math.exp(abs(rng.gauss(0, 0.004))), min(o, c) * math.exp(-abs(rng.gauss(0, 0.004)))
            vol = 200000 + (i % 3) * 100000
            rows.append(row(f"INE{i:03d}A01001", f"S{i}", o, h, l, c, pc, vol, vol * c))
            price[i] = c
        p.add_session(d, rows)
        idx_level *= math.exp(mkt)
        p.add_index_file(d, ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
                             "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
                             f"Nifty 50,{d:%d-%m-%Y},{idx_level:.2f},{idx_level:.2f},{idx_level:.2f},{idx_level:.2f},0,0,1,1,20,3,1.2\n").encode())
    p.compute_implied_factors(WeekdayCalendar())
    yield p
    p.close()


def test_panel_round_trip_and_implied_factor(panel):
    days = panel.sessions()
    assert len(days) == 900 and len(panel.isins()) == 30
    f = panel.implied_factors("INE000A01001")
    assert list(f) == [days[600]] and f[days[600]] == pytest.approx(0.5, abs=1e-9)
    assert panel.implied_factors("INE001A01001") == {}


def test_label_is_gross_and_applies_only_listed_implied_factors(panel):
    days = panel.sessions()
    d = days[590]  # window 591 .. 611 contains the bonus on day 600
    unlisted = labels.forward_return(panel, "INE000A01001", d, 20, sessions=days)
    assert unlisted.status == labels.EXCLUDED and unlisted.reason == "UNEXPLAINED_PRICE_ADJUSTMENT"  # spec 2.4
    lab = labels.forward_return(panel, "INE000A01001", d, 20, sessions=days, listed_action_days={days[600]})
    assert lab.entry_day == days[591] and lab.exit_day == days[611] and lab.factor == pytest.approx(0.5)
    eb, xb = panel.bars("INE000A01001", days[591], days[591])[0], panel.bars("INE000A01001", days[611], days[611])[0]
    assert lab.gross == pytest.approx((xb.open / 0.5) / eb.open - 1)  # no slippage inside the label
    assert lab.basis == "RECONSTRUCTED" and lab.excess is not None and lab.status == labels.RESOLVED
    # a decision on the bonus day itself: entry on day 601 is post-action, no factor applies
    assert labels.forward_return(panel, "INE000A01001", days[599], 20, sessions=days).factor == 1.0
    assert labels.forward_return(panel, "INE000A01001", days[895], 20, sessions=days).status == labels.UNRESOLVED


def test_features_hand_computed_on_a_geometric_series():
    r, n = 0.001, 400
    days = sessions(n)
    closes = [100.0 * math.exp(r * (t + 1)) for t in range(n)]
    prev = [100.0 * math.exp(r * t) for t in range(n)]
    series = {"days": days, "open": [p * math.exp(0.0005) for p in prev], "high": [c * math.exp(0.01) for c in closes],
              "low": [c * math.exp(-0.01) for c in closes], "close": closes, "prev_close": prev,
              "volume": [1000.0] * n, "value": [c * 1000 for c in closes]}
    rows = features.stock_feature_rows(series)
    f = rows[days[399]]
    assert f["mom_12_1"] == pytest.approx(230 * r, abs=1e-9) and f["rev_5"] == pytest.approx(5 * r, abs=1e-9)
    assert f["ret_20"] == pytest.approx(20 * r, abs=1e-9) and f["vol_20"] == pytest.approx(0.0, abs=1e-9)
    assert f["park_20"] == pytest.approx(0.02 / math.sqrt(4 * math.log(2)), abs=1e-9)
    assert f["gap_1"] == pytest.approx(0.0005, abs=1e-9)
    # lowest low over 250 sessions is C e^-0.259, highest high is C e^0.01
    assert f["range_250"] == pytest.approx((1 - math.exp(-0.259)) / (math.exp(0.01) - math.exp(-0.259)), abs=1e-9)
    assert days[249] not in rows and days[250] in rows  # 251 sessions of history required


def test_standardization_is_cross_sectional_and_market_features_use_training_stats():
    d = date(2024, 1, 1)
    rows = [{"day": d, "isin": str(i), "features": {**{f: float(i) for f in features.STOCK_FEATURES},
                                                   **{f: 0.5 for f in features.MARKET_FEATURES}}} for i in range(4)]
    out = features.standardize_by_date(rows, {f: (0.0, 0.1) for f in features.MARKET_FEATURES})
    assert [r["x"]["mom_12_1"] for r in out] == pytest.approx([-0.375, -0.125, 0.125, 0.375])
    assert all(r["x"]["mkt_20"] == 3.0 for r in out)  # z = 5, winsorized at +3


def test_universe_screen_applies_rules_and_reports_unverified(panel):
    days = panel.sessions()
    d = days[100]
    s = screen(panel, d, ScreenPolicy(v_min=1, W=10_000), None, days)
    assert s.unverified == ["SURVEILLANCE_UNVERIFIED", "BAND_UNVERIFIED"] and len(s.isins) == 30
    ri = {"have_reg": True, "have_band": True, "series": {"S1": "BE"}, "band": {"S2": 5.0},
          "reg": {"S3": {"suspended": True, "call_auction": False, "surveillance": frozenset()},
                  "S4": {"suspended": False, "call_auction": False, "surveillance": frozenset({"GSM:1"})},
                  "S5": {"suspended": False, "call_auction": False, "surveillance": None}}}
    s = screen(panel, d, ScreenPolicy(v_min=1, W=10_000), ri, days)
    assert s.unverified == [] and s.excluded["INE001A01001"] == "SERIES_BE" and s.excluded["INE002A01001"] == "BAND_5"
    assert s.excluded["INE003A01001"] == "SUSPENDED" and s.excluded["INE004A01001"] == "UNDER_SURVEILLANCE"
    assert s.excluded["INE005A01001"] == "SURVEILLANCE_UNKNOWN"
    assert screen(panel, d, ScreenPolicy(v_min=1e12, W=10_000), ri, days).isins == []
    assert screen(panel, d, ScreenPolicy(v_min=1, W=100), ri, days).stats.get("PRICE_ABOVE_HALF_POSITION", 0) > 0


def cfg(**kw):
    base = dict(h=20, train_sessions=400, test_sessions=60, step_sessions=60, holdout_sessions=120, bootstrap=5,
                screen=ScreenPolicy(v_min=1, W=10_000))
    base.update(kw)
    return evaluate.Config(**base)


def test_walk_forward_purges_by_outcome_date(panel):
    c = cfg()
    ds = evaluate.build_dataset(panel, c, calendar=CAL)
    assert ds.rows and ds.label_counts["EXCLUDED:UNEXPLAINED_PRICE_ADJUSTMENT"] > 0
    f = evaluate.folds(ds.sessions, c)[0]
    res = evaluate.run_fold(ds, f, c, "t", panel)
    embargo = ds.sessions[f["test_start"] - c.h]
    expected = sum(1 for r in ds.rows if ds.sessions[f["train_start"]] <= r["day"] <= ds.sessions[f["train_end"]]
                   and r["label"].exit_day < embargo)
    assert res["n_train"] == expected > 0


def test_walk_forward_report_shape_and_simulation(panel, tmp_path):
    c = cfg()
    days = panel.sessions()
    registry.freeze_holdout(tmp_path / "runs", days, c.holdout_sessions)
    report = evaluate.walk_forward(panel, c, runs=tmp_path / "runs", calendar=CAL, progress=lambda *_: None)
    assert report["folds_done"] >= 1 and report["profitability_proven"] is False
    assert report["sessions"][1] < days[-c.holdout_sessions].isoformat()  # the development view stops before the holdout
    fold = next(r for r in report["folds"] if "skipped" not in r)
    m = fold["metrics"]
    assert 0 <= m["coverage_80"] <= 1 and m["n"] > 0 and m["pit_ks"] is not None
    sim = fold["simulation"]
    assert sim["nav_liquidation"] > 0 and isinstance(sim["trades"], list) and len(sim["nav"]) == c.test_sessions
    for t in sim["trades"]:
        assert float(t["buy_value"]) <= 0.5 * c.W * (1 + 0.05) and float(t["charges"]["dp"]) == 15.34
    assert (tmp_path / "runs" / "eval" / report["trial_id"] / (report["run_id"] + ".json")).exists()
    assert report["promotion"]["verdict"] == "INSUFFICIENT EVIDENCE"  # no rule inputs: eligibility unverified


def test_holdout_fold_starts_at_the_frozen_date(panel):
    days = sessions(900)
    hold = evaluate.folds(days, cfg(evaluate_holdout=True), days[780])
    normal = evaluate.folds([d for d in days if d < days[780]], cfg(), days[780])
    assert hold == [{"train_start": 380, "train_end": 779, "test_start": 780, "test_end": 899}]
    assert all(n["test_end"] < 780 for n in normal) and normal


def test_implied_factor_needs_the_true_previous_session(tmp_path):
    p = Panel(tmp_path / "p.sqlite3")
    days = sessions(3)
    p.add_session(days[0], [row("INE000A01001", "S0", 100, 101, 99, 100, 99, 10, 1000)])
    p.add_session(days[2], [row("INE000A01001", "S0", 50, 51, 49, 50, 49.5, 10, 500)])  # looks like a halving
    out = p.compute_implied_factors(WeekdayCalendar())
    assert out["factors"] == 0 and out["unchecked_days"] == [days[0].isoformat(), days[2].isoformat()]  # day 1 missing
    p.add_session(days[1], [row("INE000A01001", "S0", 100, 101, 99, 100, 100, 10, 1000)])
    out = p.compute_implied_factors(WeekdayCalendar())
    assert out["factors"] == 1 and p.implied_factors("INE000A01001")[days[2]] == pytest.approx(0.495)
    p.close()
