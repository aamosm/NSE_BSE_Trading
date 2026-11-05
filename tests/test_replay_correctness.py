"""Checkpoint B: replay correctness (review of 114589a). Synthetic fixtures only; every expected value is derived
in the test from prices and the fee schedule, independently of the ledger's own arithmetic."""
import json
import math
import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from marketlab.costs import charges
from marketlab.quant import allocate, evaluate, features, labels, registry, replay
from marketlab.quant.allocate import Candidate, Policy
from marketlab.quant.ledger import ExecutionPolicy, Intent, Ledger, money, reservation
from marketlab.quant.panel import Bar, Panel
from marketlab.quant.sessions import exchange_sessions
from marketlab.quant.universe import ScreenPolicy, screen
from synthetic import WeekdayCalendar, index_csv, isin, make_panel, row, sessions

CAL = WeekdayCalendar()
X = "INE900A01001"
POL = Policy.for_capital(10_000)  # K 2, cap Rs 5,000, reserve Rs 2,000


def tiny_panel(path, n, series, index=None, start=date(2024, 1, 1), value=2e8, names=None):
    """series: {isin: [(open, high, low, close) or None per session]}; prev_close = the last traded close."""
    days = sessions(n, start)
    p = Panel(path)
    last = {}
    for t, d in enumerate(days):
        rows = []
        for j, (code, bars) in enumerate(series.items()):
            b = bars[t]
            if b is None:
                continue
            o, h, l, c = b
            rows.append(row(code, f"S{j}", o, h, l, c, last.get(code, o), 1e6, value,
                            name=(names or {}).get((code, t), "X LIMITED")))
            last[code] = c
        p.add_session(d, rows)
        io, ic = index[t] if index else (10000.0, 10000.0)
        p.add_index_file(d, index_csv(d, ic, io))
    p.compute_implied_factors(CAL)
    return p, days


def flat(n, px=250.0):
    return [(px, px * 1.01, px * 0.99, px)] * n


def fc(close, mu=0.03):
    return {"mu_hat": mu, "se": 0.0, "mu_shrunk": mu, "sigma_hat": 0.05, "q10": -0.03, "q50": mu, "q90": 0.09,
            "p_positive": 0.7, "ref_close": close, "symbol": "S0", "median_value": 2e8}


def forecasts(days, D, **kw):
    out = {d: {} for d in days}
    out[days[D]] = {X: fc(250.0, **kw)}
    return out


# ---- 1. the intent is frozen before the next open -----------------------------------------------------------

def test_two_histories_equal_through_monday_give_the_same_monday_intent(tmp_path):
    n, D = 12, 5
    a, b = flat(n), flat(n)
    a[D + 1] = (252.0, 255.0, 251.0, 253.0)  # a small gap: fills at 252 x 1.001 <= limit 262.50
    b[D + 1] = (270.0, 275.0, 268.0, 272.0)  # a big gap: 270.27 > limit, rejected under the rule declared on Monday
    pa, days = tiny_panel(tmp_path / "a.sqlite3", n, {X: a})
    pb, _ = tiny_panel(tmp_path / "b.sqlite3", n, {X: b})
    ra = replay.simulate(pa, days, set(days), D, D + 3, forecasts(days, D), policy=POL, h=20)
    rb = replay.simulate(pb, days, set(days), D, D + 3, forecasts(days, D), policy=POL, h=20)
    ia, ib = ([e for e in r["events"] if e["event"] == "INTENT"] for r in (ra, rb))
    assert ia == ib and ia[0]["q"] == 20 and ia[0]["ref_close"] == 250.0 and ia[0]["limit"] == 262.5
    assert ia[0]["reserved"] == str(reservation(20, 262.5))  # funds blocked at the limit, before any open is known
    assert ra["event_counts"]["FILLED"] == 1 and rb["event_counts"]["REJECTED_GAP"] == 1 and "FILLED" not in rb["event_counts"]
    assert ra["nav"][0] == rb["nav"][0] and ra["nav"][0]["nav"] == 10_000.0 and ra["nav"][0]["positions"] == 0  # no Monday P&L
    assert rb["nav"][1]["nav"] == 10_000.0 and rb["nav"][1]["blocked"] == 0.0 and rb["n_trades"] == 0  # released
    fill = next(e for e in ra["events"] if e["event"] == "FILLED")
    assert fill["day"] == days[D + 1].isoformat() and fill["value"] == str(money(20 * 252.0 * 1.001))


def test_an_untradable_entry_is_deferred_then_fails_without_a_fictional_fill(tmp_path):
    n, D = 12, 5
    s = flat(n)
    for t in range(D + 1, D + 5):
        s[t] = None  # suspended for four sessions
    pn, days = tiny_panel(tmp_path / "p.sqlite3", n, {X: s})
    r = replay.simulate(pn, days, set(days), D, D + 5, forecasts(days, D), policy=POL, h=20)
    assert r["event_counts"]["FILL_DEFERRED"] == 3 and r["event_counts"]["ENTRY_FAILED"] == 1  # spec 2.2: > 3 sessions
    assert all(row["nav"] == 10_000.0 and row["positions"] == 0 for row in r["nav"]) and r["n_trades"] == 0


def test_a_session_missing_from_the_data_cancels_the_entry(tmp_path):
    n, D = 12, 5
    pn, days = tiny_panel(tmp_path / "p.sqlite3", n, {X: flat(n)})
    have = set(days) - {days[D + 1]}  # the calendar says it was a session; we do not hold it
    r = replay.simulate(pn, days, have, D, D + 3, forecasts(days, D), policy=POL, h=20)
    assert r["event_counts"]["CANCELLED_DATA_GAP"] == 1 and r["n_trades"] == 0


def test_a_blocked_exit_stays_in_the_books_with_outcome_bounds(tmp_path):
    n, D, h = 12, 5, 3
    s = flat(n)
    for t in range(9, n):
        s[t] = None  # suspended from the exit session on
    pn, days = tiny_panel(tmp_path / "p.sqlite3", n, {X: s})
    r = replay.simulate(pn, days, set(days), D, n - 1, forecasts(days, D), policy=POL, h=h)
    decided = next(e for e in r["events"] if e["event"] == "EXIT_DECIDED")
    assert decided["day"] == days[8].isoformat() and decided["reason"] == "NO_CONTINUATION_FORECAST"  # review at entry+h-1
    assert r["event_counts"]["EXIT_BLOCKED"] == 3 and r["n_trades"] == 0
    (op,) = r["open_positions"]
    assert op["status"] == "EXIT_BLOCKED" and op["outcome_bounds"][0] == 0.0 and op["outcome_bounds"][1] == float(op["liquidation_value"])
    assert r["nav"][-1]["stale_marks"] == 1 and r["nav"][-1]["positions"] == 20 * 250.0  # marked at the last known close
    assert r["nav_liquidation_lower_bound"] < r["nav_liquidation"]


# ---- 2. the opportunity set is built before outcomes are looked at ------------------------------------------

def test_a_future_suspension_does_not_change_the_decision_time_universe(tmp_path):
    kw = dict(n=320, n_stocks=8, bonus_at=10_000)
    base = make_panel(tmp_path / "a.sqlite3", **kw)
    susp = make_panel(tmp_path / "b.sqlite3", drop=lambda t, i: i == 3 and t >= 300, **kw)
    cfg = evaluate.Config(h=20, screen=ScreenPolicy(v_min=1, W=10_000))
    da, db = (evaluate.build_dataset(p, cfg, calendar=CAL) for p in (base, susp))
    d = da.sessions[290]  # the label window 291..311 crosses the suspension; the decision does not
    assert da.universe[d].isins == db.universe[d].isins and isin(3) in db.universe[d].isins
    oa = next(o for o in da.opportunities if o["day"] == d and o["isin"] == isin(3))
    ob = next(o for o in db.opportunities if o["day"] == d and o["isin"] == isin(3))
    assert oa["features"] == ob["features"] and oa["label"].status == labels.RESOLVED
    assert ob["label"].status == labels.EXCLUDED and ob["label"].reason == "NO_TRADE_AT_EXIT"  # statistical exclusion only
    base.close()
    susp.close()


def test_the_horizon_counts_exchange_sessions_and_a_data_gap_is_unknown(tmp_path):
    pn = make_panel(tmp_path / "g.sqlite3", n=320, n_stocks=6, bonus_at=10_000, skip_days={300})
    stored = set(pn.sessions())
    sess, basis = exchange_sessions(CAL, min(stored), max(stored), stored)
    assert len(sess) == 320 and sess[300] not in stored and basis == {2020: "CALENDAR", 2021: "CALENDAR"}
    lab = labels.forward_return(pn, isin(1), sess[290], 20, sessions=sess, panel_days=stored)
    assert lab.status == labels.EXCLUDED and lab.reason == "DATA_GAP" and lab.exit_day == sess[311]  # not stretched to 312
    ok = labels.forward_return(pn, isin(1), sess[270], 20, sessions=sess, panel_days=stored)
    assert ok.status == labels.RESOLVED and ok.exit_day == sess[291]
    s = screen(pn, sess[305], ScreenPolicy(v_min=1, W=10_000), None, sess, stored)
    assert s.isins == [] and s.unverified == ["PANEL_GAP_IN_LOOKBACK"]  # rule 2 cannot be verified across the gap
    pn.close()


def test_rule_files_are_those_of_the_entry_session_and_eligibility_is_dated(tmp_path):
    names = {(X, 0): "ABC LIMITED", (X, 1): "ABC LIMITED", (X, 2): "ABC ETF"}  # renamed later
    pn, days = tiny_panel(tmp_path / "e.sqlite3", 3, {X: flat(3)}, names=names)
    assert pn.is_etf(X, days[1]) is False and pn.is_etf(X, days[2]) is True
    big = make_panel(tmp_path / "r.sqlite3", n=60, n_stocks=4, bonus_at=10_000)
    seen = []
    evaluate.build_dataset(big, evaluate.Config(screen=ScreenPolicy(v_min=1, W=10_000)), calendar=CAL,
                           rule_inputs_fn=lambda d: seen.append(d) or None)
    stored = big.sessions()
    assert seen[0] == stored[1] and seen[-1] == CAL.next_trading_day(None, stored[-1])  # D's screen uses D+1's files
    big.close()


# ---- 3. live and replay features agree; missing stays missing --------------------------------------------------

def test_features_as_of_a_day_do_not_depend_on_later_data(tmp_path):
    short = make_panel(tmp_path / "s.sqlite3", n=300, n_stocks=10, bonus_at=10_000)
    long_ = make_panel(tmp_path / "l.sqlite3", n=340, n_stocks=10, bonus_at=10_000)
    cfg = evaluate.Config(h=20, screen=ScreenPolicy(v_min=1, W=10_000))
    ds, dl = (evaluate.build_dataset(p, cfg, calendar=CAL) for p in (short, long_))
    d = ds.sessions[-1]  # the live decision day of the short history
    rows_s = {o["isin"]: o for o in ds.opportunities if o["day"] == d}
    rows_l = {o["isin"]: o for o in dl.opportunities if o["day"] == d}
    assert rows_s and rows_s.keys() == rows_l.keys()
    for k in rows_s:
        fs, fl = rows_s[k]["features"], rows_l[k]["features"]
        assert fs.keys() == fl.keys() and rows_s[k]["missing"] == rows_l[k]["missing"] == []
        assert all(fs[f] == pytest.approx(fl[f], rel=1e-12, abs=1e-15) for f in fs)  # breadth from 50 sessions in both
    assert math.isfinite(rows_s[next(iter(rows_s))]["features"]["breadth_50"])
    short.close()
    long_.close()


def test_a_missing_market_feature_is_not_clipped_to_plus_three():
    row_ = {"day": date(2024, 1, 1), "isin": "X", "features": {**{f: 0.1 for f in features.STOCK_FEATURES},
                                                             "mkt_20": 0.5, "mkt_60": 0.5, "mkt_vol_20": 0.5,
                                                             "breadth_50": float("nan")}}
    out = features.standardize_by_date([row_], {f: (0.0, 0.1) for f in features.MARKET_FEATURES})
    assert out[0]["x"]["mkt_20"] == 3.0 and math.isnan(out[0]["x"]["breadth_50"])
    assert features.missing_features(out[0]["x"]) == ["breadth_50"]  # the decision abstains (FEATURE_COVERAGE)


# ---- 4. costs and slippage are counted once, at the actual quantity -----------------------------------------

def _exact(value, side):
    v = money(value)
    return sum(charges(v, side=side, style="delivery", dp=(side == "SELL")).values(), Decimal("0"))


def _round_trip(q, entry_open, exit_open, idx_entry, idx_exit, day0=date(2024, 3, 1)):
    led = Ledger(10_000, ExecutionPolicy())
    led.add_intent(Intent("t", X, "S0", day0, q, entry_open, entry_open * 1.05, 0.001, 0.001,
                          reservation(q, entry_open * 1.05), 1, {"q10": -0.5}))
    d1, d2 = day0 + timedelta(days=1), day0 + timedelta(days=2)
    led.execute_entries(1, d1, True, {X: Bar(d1, "S0", "EQ", entry_open, entry_open * 1.01, entry_open * 0.99, entry_open,
                                             entry_open * 0.999, 1e6, 2e8, 10)}, 20, idx_entry)
    lot = led.lots[X]
    lot.exit_pending, lot.exit_decided_index, lot.exit_reason = True, 1, "TEST"
    led.execute_exits(2, d2, True, {X: Bar(d2, "S0", "EQ", exit_open, exit_open, exit_open * 0.99, exit_open,
                                           exit_open, 1e6, 2e8, 10)}, idx_exit)
    return led.trades[0], led


@pytest.mark.parametrize("q", [20, 2])
def test_flat_market_round_trip_reconciles_gross_slippage_charges_and_net(q):
    t, _ = _round_trip(q, 250.0, 260.0, 10_000.0, 10_000.0)
    buy_v, sell_v = money(q * 250.0 * 1.001), money(q * 260.0 * 0.999)
    assert Decimal(t["buy_value"]) == buy_v and Decimal(t["sell_value"]) == sell_v
    assert t["gross_rupees_at_open"] == pytest.approx(q * 10.0)
    assert t["slippage_rupees"] == pytest.approx(q * 250.0 * 0.001 + q * 260.0 * 0.001)
    expected_charges = _exact(buy_v, "BUY") + _exact(sell_v, "SELL")  # DP Rs 15.34 once, on the sell day
    assert Decimal(t["charges"]["total"]) == expected_charges and Decimal(t["charges"]["dp"]) == Decimal("15.34")
    assert t["net_rupees"] == pytest.approx(float(sell_v - buy_v - expected_charges), abs=1e-9)
    assert t["net_rupees"] == pytest.approx(t["gross_rupees_at_open"] - t["slippage_rupees"] - float(expected_charges), abs=0.02)
    assert t["abs_return_gross"] == pytest.approx(0.04) and t["index_return"] == 0.0
    assert t["active_return_log"] == pytest.approx(math.log(1.04))


def test_the_fixed_charge_makes_the_small_quantity_much_worse_per_rupee():
    big, _ = _round_trip(20, 250.0, 260.0, 10_000.0, 10_000.0)
    small, _ = _round_trip(2, 250.0, 260.0, 10_000.0, 10_000.0)
    assert big["net_return"] > 0.03 and small["net_return"] < 0.005  # same 4% move, DP Rs 15.34 dominates 2 shares


def test_in_a_falling_market_a_positive_active_return_can_still_lose_money():
    t, _ = _round_trip(20, 250.0, 247.5, 10_000.0, 9_500.0)
    assert t["abs_return_gross"] == pytest.approx(-0.01) and t["index_return"] == pytest.approx(-0.05)
    assert t["active_return_log"] == pytest.approx(math.log(0.99) - math.log(0.95)) and t["active_return_log"] > 0
    assert t["net_rupees"] < 0  # excess return and net rupee profit are different events


def test_a_plan_rechecks_the_gate_at_the_whole_share_quantity():
    # review boundary case: cap Rs 5,000, slippage 0.20%, minimum edge 0.10%
    assert allocate.break_even(5000) + 0.002 + 0.001 == pytest.approx(0.008293, abs=1e-6)
    assert allocate.break_even(4200) + 0.002 + 0.001 == pytest.approx(0.0088774, abs=1e-6)
    c = Candidate("INE000A01001", 2100.0, 0.0086, 0.05)
    assert allocate.entry_gate(c, POL) == (True, [])  # the preliminary gate at Rs 5,000 passes...
    reasons, at_q = allocate.position_gate(c, 2, POL)  # ...but two shares are only Rs 4,200
    assert reasons == ["EDGE_BELOW_COST_AT_QUANTITY"] and at_q["net_edge"] < POL.min_edge
    plan = allocate.plan([c], [[1.0]], POL, 8_000)
    assert plan["quantities"] == {} and plan["rejected"]["INE000A01001"] == ["EDGE_BELOW_COST_AT_QUANTITY"]
    ok = allocate.plan([replace(c, mu=0.0095)], [[1.0]], POL, 8_000)
    assert ok["quantities"] == {"INE000A01001": 2} and ok["positions"]["INE000A01001"]["net_edge"] >= POL.min_edge


# ---- 5. open positions, unsettled cash, corporate actions in the ledger -------------------------------------

def test_sale_proceeds_count_in_nav_but_fund_nothing_until_settled():
    t, led = _round_trip(20, 250.0, 260.0, 10_000.0, 10_000.0)
    (r,) = led.receivables
    assert r["usable_from"] == 3  # T+1 (2024): usable from the decision after the next session
    led.mark(2, date(2024, 3, 3), {}, True)
    assert led.nav[-1]["unsettled"] == float(r["amount"]) and led.nav[-1]["nav"] == pytest.approx(10_000 + t["net_rupees"])
    before = led.available_cash(2_000)
    led.settle(3, date(2024, 3, 4))
    assert led.available_cash(2_000) == pytest.approx(before + float(r["amount"])) and not led.receivables
    _, old = _round_trip(20, 250.0, 260.0, 10_000.0, 10_000.0, day0=date(2022, 3, 1))
    assert old.receivables[0]["usable_from"] == 4  # T+2 before 27 Jan 2023


def test_a_bonus_while_held_doubles_the_units_and_is_flagged_unless_listed(tmp_path):
    n, D, h = 12, 2, 6
    s = flat(n)
    s[6] = (125.0, 126.0, 124.0, 125.0)  # ex-date of a 1:1 bonus: the base price halves
    s[6:] = [(125.0, 126.0, 124.0, 125.0)] * (n - 6)
    pn, days = tiny_panel(tmp_path / "b.sqlite3", n, {X: s})
    pn.db.execute("UPDATE bars SET prev_close = 125.0 WHERE day = ?", (days[6].isoformat(),))  # exchange base price
    pn.db.commit()
    pn.compute_implied_factors(CAL)
    assert pn.implied_factors(X)[days[6]] == pytest.approx(0.5)
    r = replay.simulate(pn, days, set(days), D, n - 1, forecasts(days, D), policy=POL, h=h)
    trade = r["trades"][0] if r["trades"] else None
    held = r["open_positions"][0] if not trade else None
    units = trade["units_exit"] if trade else held["units"]
    status = (trade or held)["action_status"]
    assert units == 40.0 and status == "FACTOR_UNVERIFIED"
    assert r["nav"][4]["positions"] == pytest.approx(r["nav"][3]["positions"], rel=0.01)  # value continuous over the ex-date
    listed = replay.simulate(pn, days, set(days), D, n - 1, forecasts(days, D), policy=POL, h=h,
                             listed=lambda i, d: d == days[6])
    assert ((listed["trades"] or listed["open_positions"])[0])["action_status"] == "FACTOR_LISTED"
    pn.close()


# ---- 6. the holdout is isolated by date and by immutable artifacts ------------------------------------------

def _holdout_cfg(**kw):
    return evaluate.Config(h=20, train_sessions=250, test_sessions=50, step_sessions=50, holdout_sessions=100, bootstrap=0,
                           screen=ScreenPolicy(v_min=1, W=10_000), **kw)


def _canonical(rep):
    drop = {"generated_at", "run_id", "path", "promotion"}
    return json.dumps({k: v for k, v in rep.items() if k not in drop}, sort_keys=True, default=str)


def test_changing_or_appending_holdout_prices_leaves_development_results_unchanged(tmp_path):
    pn = make_panel(tmp_path / "h.sqlite3", n=700, n_stocks=12, bonus_at=10_000)
    runs = tmp_path / "runs"
    man = registry.freeze_holdout(runs, pn.sessions(), 100)
    hs = man["holdout_start"]
    cfg = _holdout_cfg()
    first = evaluate.walk_forward(pn, cfg, runs=runs, calendar=CAL, progress=lambda *_: None)
    assert first["folds_done"] >= 2 and first["sessions"][1] < hs and first["data_end"] < hs
    con = sqlite3.connect(tmp_path / "h.sqlite3")
    with con:
        con.execute("UPDATE bars SET open = open * 1.3, high = high * 1.3, low = low * 1.3, close = close * 1.3 WHERE day >= ?", (hs,))
        last = con.execute("SELECT max(day) FROM sessions").fetchone()[0]
        nxt = date.fromisoformat(last) + timedelta(days=3)
        con.execute("INSERT INTO sessions VALUES (?, '')", (nxt.isoformat(),))
        con.execute("INSERT INTO bars SELECT isin, ?, symbol, series, name, open, high, low, close, prev_close, volume, value, trades "
                    "FROM bars WHERE day = ?", (nxt.isoformat(), last))
    con.close()
    assert registry.freeze_holdout(runs, pn.sessions(), 100)["holdout_start"] == hs  # the holdout never moves
    second = evaluate.walk_forward(pn, cfg, runs=runs, calendar=CAL, progress=lambda *_: None)
    assert second["manifest_hash"] == first["manifest_hash"] and _canonical(second) == _canonical(first)
    assert first["run_id"] != second["run_id"] and len(list((runs / "eval" / first["trial_id"]).glob("*.json"))) == 2
    hold = evaluate.walk_forward(pn, replace(cfg, evaluate_holdout=True), runs=runs, calendar=CAL, progress=lambda *_: None)
    assert hold["holdout"] is True and hold["folds"][0]["fold"]["test_start"] >= hs
    with pytest.raises(ValueError, match="HOLDOUT_ALREADY_EVALUATED"):
        evaluate.walk_forward(pn, replace(cfg, evaluate_holdout=True), runs=runs, calendar=CAL, progress=lambda *_: None)
    pn.close()


def test_evaluation_refuses_to_run_without_a_frozen_holdout(tmp_path):
    pn = make_panel(tmp_path / "x.sqlite3", n=40, n_stocks=3, bonus_at=10_000)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_FROZEN"):
        evaluate.walk_forward(pn, _holdout_cfg(), runs=tmp_path / "runs", calendar=CAL, progress=lambda *_: None)
    with pytest.raises(ValueError, match="HOLDOUT_TOO_EARLY"):
        registry.freeze_holdout(tmp_path / "runs", pn.sessions(), 100)
    pn.close()


# ---- 7. every frozen promotion criterion, or insufficient evidence ------------------------------------------

def _report(sign=1.0, verified=True, one_stock=False, holdout=150.0):
    folds = []
    for f in range(4):
        days = [(date(2022 + f % 3, 1, 3) + timedelta(days=i)).isoformat() for i in range(60)]
        trades = [{"isin": "INE001A01001" if one_stock else f"INE{(f * 100 + j) % 40:03d}A01001",
                   "net_rupees": sign * (30.0 + (j % 7) * 5), "net_return": sign * (0.006 + (j % 7) * 0.001),
                   "entry_day": days[j % 60], "exit_day": days[(j + 5) % 60]} for j in range(100)]
        nav = [{"day": d, "nav": 10_000 + sign * i, "positions": 5_000.0} for i, d in enumerate(days)]
        net = sum(t["net_rupees"] for t in trades)
        folds.append({"fold": {"test_start": days[0], "test_end": days[-1]},
                      "evidence": {"verified": verified},
                      "metrics": {"coverage_80": 0.8, "n": 500, "brier_skill": 0.05, "residual_icc_by_date": 0.1},
                      "simulation": {"net_rupees": net, "trades": trades, "nav": nav, "open_positions": [],
                                     "policy": {"W": 10_000}},
                      "stresses": {"costs_x2": sign * 10, "slippage_x2": sign * 10, "entry_one_session_late": sign * 10,
                                   "best_5pct_trades_removed": sign * 10}})
    daily = {r["day"]: sign * 0.001 for f in folds for r in f["simulation"]["nav"]}
    rep = {"trial_id": "A.h20.mine", "config": {"h": 20}, "folds": folds, "attribution": {"beta": 0.4},
           "pooled": {"sharpe_per_trade": 1.5 * sign}, "daily_returns": daily}
    other = {"trial_id": "A.h60.other", "pooled": {"sharpe_per_trade": 0.2}, "daily_returns": {d: -0.0005 for d in daily}}
    return rep, other, ({"net_rupees_total": holdout} if holdout is not None else None)


def test_all_criteria_pass_only_with_complete_evidence():
    rep, other, hold = _report()
    v = evaluate.promotion(rep, registry_reports=[rep, other], holdout_report=hold)
    assert v["verdict"] == "PROMOTED" and all(c is True for c in v["criteria"].values()), v["criteria"]
    assert v["pbo"]["pbo"] == 0.0 and v["dsr"] >= 0.95 and v["n_eff"]["n_eff"] < 400  # N_eff, not the raw trade count


@pytest.mark.parametrize("change, missing", [
    (dict(holdout=None), "holdout_net_positive"),  # the single holdout evaluation has not happened
    (dict(verified=False), "verified_folds_exist"),  # unverified eligibility cannot support promotion
])
def test_missing_evidence_gives_insufficient_evidence(change, missing):
    rep, other, hold = _report(**change)
    v = evaluate.promotion(rep, registry_reports=[rep, other], holdout_report=hold)
    assert v["verdict"] == "INSUFFICIENT EVIDENCE" and v["criteria"][missing] is None


def test_without_a_trial_registry_pbo_and_dsr_are_missing():
    rep, _, hold = _report()
    v = evaluate.promotion(rep, registry_reports=[rep], holdout_report=hold)
    assert v["criteria"]["pbo_le_025"] is None and v["criteria"]["dsr_95"] is None and v["verdict"] == "INSUFFICIENT EVIDENCE"


def test_concentration_and_losses_reject_when_the_evidence_is_conclusive():
    rep, other, hold = _report(one_stock=True)
    v = evaluate.promotion(rep, registry_reports=[rep, other], holdout_report=hold)
    assert v["criteria"]["no_year_or_stock_over_half"] is False and v["verdict"] == "REJECT"
    rep, other, hold = _report(sign=-1.0, holdout=-50.0)
    v = evaluate.promotion(rep, registry_reports=[rep, other], holdout_report=hold)
    assert v["criteria"]["net_positive_pooled"] is False and v["criteria"]["n_eff_ge_mintrl"] is True
    assert v["verdict"] == "REJECT"


def test_a_promotion_record_verifies_only_with_untouched_reports(tmp_path):
    runs = tmp_path / "runs"
    crit = {k: True for k in ("verified_folds_exist", "net_positive_pooled", "dsr_95")} | {"holdout_net_positive": None}
    dev = {"trial_id": "A.h20.t", "manifest_hash": "m", "policy_digest": "p", "holdout": False, "promotion": {"criteria": crit}}
    hold = {"trial_id": "A.h20.t", "manifest_hash": "m", "policy_digest": "p", "holdout": True, "net_rupees_total": 12.5}
    for kind, rep in (("eval", dev), ("holdout", hold)):
        (runs / kind / "A.h20.t").mkdir(parents=True)
        (runs / kind / "A.h20.t" / "r1.json").write_text(json.dumps(rep))
    rec = registry.write_promotion(runs, runs / "eval/A.h20.t/r1.json", runs / "holdout/A.h20.t/r1.json", "A", 20)
    assert rec and registry.verified_promotion(runs, "A", 20, "p")[0]["promotion_id"] == rec["promotion_id"]
    assert registry.verified_promotion(runs, "A", 20, "another-policy")[0] is None
    (runs / "holdout/A.h20.t/r1.json").write_text(json.dumps(hold | {"net_rupees_total": 99.0}))
    found, problems = registry.verified_promotion(runs, "A", 20, "p")
    assert found is None and "HOLDOUT_REPORT_HASH_MISMATCH" in problems
    bad = dict(dev, promotion={"criteria": crit | {"dsr_95": None}})
    (runs / "eval/A.h20.t/r2.json").write_text(json.dumps(bad))
    assert registry.write_promotion(runs, runs / "eval/A.h20.t/r2.json", runs / "holdout/A.h20.t/r1.json", "A", 20) is None


# ---- 8. the live decision is the replay path; the dashboard reads the immutable reports ---------------------

def test_the_live_decision_uses_the_replay_rows_and_records_whole_share_intents(tmp_path):
    from marketlab.quant import decide
    pn = make_panel(tmp_path / "d.sqlite3", n=400, n_stocks=30, bonus_at=10_000)
    root = tmp_path / "private"
    root.mkdir()
    cfg = evaluate.Config(h=20, train_sessions=200, screen=ScreenPolicy(v_min=1, W=10_000))
    out = decide.run(pn, cfg, root=root, origin="cli", calendar=CAL, bootstrap=0)
    rec = out["record"]
    ds = evaluate.build_dataset(pn, cfg, calendar=CAL)
    today = [o for o in ds.opportunities if o["day"] == ds.sessions[-1] and not o["missing"]]
    diag = json.loads((tmp_path / "runs" / rec["diagnostic_artifact"]).read_text(encoding="utf-8"))
    assert rec["action"] == "WAIT" and rec["reasons"][0] == "MODEL_NOT_PROMOTED" and rec["integrity"] == "OK"
    assert rec["data"]["manifest_hash"] == ds.manifest_hash and len(diag["forecasts"]) == len(today) > 0
    assert diag["feature_coverage_missing"] == 0 and diag["plan_status"] == "DIAGNOSTIC_NOT_PROMOTED"
    for it in diag["intents"]:
        assert float(it["cash_blocked"]) <= 8_000 and it["costs_at_q"]["net_edge"] >= 0.001 and it["costs_at_q"]["value"] <= 5_000
    pn.close()


def test_the_dashboard_lists_and_opens_immutable_reports(tmp_path, monkeypatch):
    from marketlab import webapp
    rep, other, _ = _report()
    runs = tmp_path / "runs"
    for r in (rep, other):
        (runs / "eval" / r["trial_id"]).mkdir(parents=True)
        (runs / "eval" / r["trial_id"] / "run1.json").write_text(json.dumps(r | {"run_id": "run1"}), encoding="utf-8")
    monkeypatch.setattr(webapp, "RUNS", runs)
    listing = webapp.evaluation_view(None, tmp_path / "private")
    assert [r["key"] for r in listing["reports"]] == ["eval/A.h20.mine/run1", "eval/A.h60.other/run1"]
    full = webapp.evaluation_view("eval/A.h20.mine/run1", tmp_path / "private")
    assert full["trial_id"] == "A.h20.mine" and full["kind"] == "development"
    assert webapp.evaluation_view("eval/../../secret", tmp_path / "private") == {"error": "NOT_FOUND"}
