from datetime import datetime, timedelta
from decimal import Decimal as D
from dataclasses import replace
import json
import pytest
from hypothesis import given, strategies as st, settings

from marketlab.backtest import Bar, simulate, walk_forward_ranges, load_bars, compare
from marketlab.costs import charges, total_charges
from marketlab.common import IST
from marketlab.cli import demo, import_trades
from marketlab.audit import audit_dataset
from marketlab.store import Store


def bars(prices):
    start = datetime(2026, 11, 1, tzinfo=IST)
    return [Bar(start+timedelta(days=i), start+timedelta(days=i,hours=16),
                start+timedelta(days=i,hours=16), D(str(p)), D(str(p+1)), D(str(p-1)), D(str(p)), 100000)
            for i, p in enumerate(prices)]


def test_independent_nse_delivery_fees():
    # 1,000 buy: STT 1; txn .0307; stamp .15; SEBI .001; GST .005706...
    assert total_charges(1000, side="BUY", style="delivery") == D("1.19")
    assert total_charges(1000, side="SELL", style="delivery", dp=True) == D("16.38")


def test_intraday_brokerage_stt_and_no_dp():
    c = charges(1000, side="BUY", style="intraday", dp=True)
    s = charges(1000, side="SELL", style="intraday", dp=True)
    assert c["brokerage"] == s["brokerage"] == D(".30")
    # 0.025% of 1,000 = 0.25; STT is rounded to the rupee (under 50 paise rounds down) -> 0
    assert c["stt"] == 0 and s["stt"] == D("0")
    assert c["dp"] == s["dp"] == 0


def test_bse_group_is_mandatory_and_changes_cost():
    with pytest.raises(ValueError):
        charges(10000, side="BUY", style="delivery", exchange="BSE")
    a = total_charges(10000, side="BUY", style="delivery", exchange="BSE", bse_group="A")
    x = total_charges(10000, side="BUY", style="delivery", exchange="BSE", bse_group="X")
    assert x > a


def test_no_mtf_or_derivatives_style_is_accepted():
    with pytest.raises(ValueError):
        charges(1000, side="BUY", style="MTF")
    with pytest.raises(ValueError):
        charges(1000, side="BUY", style="delivery", exchange="NFO")


def test_first_signal_fills_at_next_bar_open_not_prior_close():
    b = bars([100, 120, 140])
    r = simulate(b, strategy="buy_hold", slippage_bps=0)
    assert r["trades"][0]["at"] == str(b[1].start)
    assert r["trades"][0]["price"] == "120.00"
    assert r["decisions"][0]["known_bars"] == 0


def test_late_price_availability_blocks_early_decisions():
    b = bars([100, 120, 140])
    b[0] = replace(b[0], available_at=b[2].end)
    r = simulate(b, strategy="buy_hold")
    assert r["decisions"][1]["known_bars"] == 0
    assert r["trades"][0]["at"] == str(b[2].start)


def test_future_prices_do_not_change_earlier_decisions_or_fills():
    original = bars([100,101,102,103,104,105,106,107])
    modified = original[:5] + [replace(b, open=D(200), high=D(201), low=D(199), close=D(200)) for b in original[5:]]
    a, b = (simulate(x, lookback=2) for x in (original, modified))
    assert a["decisions"][:5] == b["decisions"][:5]
    cutoff = str(original[5].start)
    assert [x for x in a["trades"] if x["at"] < cutoff] == [x for x in b["trades"] if x["at"] < cutoff]


def test_unsettled_receipts_do_not_increase_spendable_cash():
    r = simulate(bars([100,110,90,120,130,80,140]), strategy="trend", lookback=2, slippage_bps=0)
    assert any(D(x["unsettled"]) > 0 for x in r["equity_curve"])
    for x in r["equity_curve"]:
        assert D(x["cash"]) >= 0
        assert D(x["cash"]) + D(x["unsettled"]) + D(x["shares"])*D(str([100,110,90,120,130,80,140][r["equity_curve"].index(x)])) == D(x["nav"])


def test_no_forced_end_of_sample_delivery_liquidation():
    r = simulate(bars([100,101,102]), strategy="buy_hold")
    assert r["equity_curve"][-1]["shares"] > 0
    assert len(r["trades"]) == 1
    assert D(r["estimated_exit_cost_on_open_position"]) > 0


def test_pnl_reconciles_on_flat_position():
    r = simulate(bars([100,110,90,80,70]), strategy="trend", lookback=2, slippage_bps=0)
    flow = D("0")
    for t in r["trades"]:
        value = D(t["price"])*t["qty"]
        flow += value if t["side"] == "SELL" else -value
        flow -= D(t["fees"])
    assert r["equity_curve"][-1]["shares"] == 0
    assert flow == D(r["net_pnl_after_fixed_cost"])


def intraday():
    day = datetime(2026,11,4,9,30,tzinfo=IST)
    times = [day, day+timedelta(minutes=5), day+timedelta(minutes=10), day.replace(hour=15,minute=5)]
    prices = [100,90,91,92]
    return [Bar(t,t+timedelta(minutes=5),t+timedelta(minutes=5),D(p),D(p+1),D(p-1),D(p),100000) for t,p in zip(times,prices)]


def test_intraday_exits_at_predeclared_time_with_intraday_fees():
    r = simulate(intraday(), strategy="intraday_reversal", lookback=2, slippage_bps=0)
    assert [t["side"] for t in r["trades"]] == ["BUY","SELL"]
    assert r["trades"][-1]["reason"] == "SCHEDULED_INTRADAY_EXIT"
    assert r["equity_curve"][-1]["shares"] == 0


def test_missing_intraday_exit_is_failure_not_a_fictitious_fill():
    with pytest.raises(ValueError, match="open intraday"):
        simulate(intraday()[:-1], strategy="intraday_reversal", lookback=2)


def test_same_day_delivery_exit_is_explicitly_unsupported():
    b = intraday()
    b[1] = replace(b[1], open=D(110), high=D(111), low=D(109), close=D(110))
    b[2] = replace(b[2], open=D(90), high=D(91), low=D(89), close=D(90))
    r = simulate(b, strategy="trend", lookback=2)
    assert any(t["side"] == "BUY" for t in r["trades"])
    assert r["decisions"][-1]["reason"] == "SAME_DAY_DELIVERY_NETTING_UNSUPPORTED"
    assert not any(t["side"] == "SELL" for t in r["trades"])


def test_failed_experiments_remain_in_registry(tmp_path):
    from marketlab.experiments import Experiment
    from marketlab.common import now
    source = tmp_path/"prices.csv"
    source.write_text("invalid")
    with pytest.raises(ValueError):
        with Experiment(tmp_path, source, {"name": "failed-fixture"}) as run:
            raise ValueError("deliberate failure")
    db = Store(tmp_path/"evidence.sqlite3")
    events = db.as_of("run_event", run.run_id, now())
    assert [x["payload"]["state"] for x in events] == ["STARTED", "FAILED"]
    assert events[0]["payload"]["dataset_sha256"]
    db.close()


def test_walk_forward_has_no_overlap_and_preserves_embargo():
    folds = list(walk_forward_ranges(120, 50, 20, 5))
    assert folds == [(0,50,55,75),(0,70,75,95),(0,90,95,115)]


def test_demo_and_audit_are_labelled_and_deterministic(tmp_path):
    a = demo(tmp_path)
    b = compare(tmp_path/"synthetic_daily.csv")
    assert a["comparison"] == b["comparison"]
    assert a["data_origin"].startswith("SYNTHETIC")
    audit = audit_dataset(tmp_path/"synthetic_daily.csv")
    assert audit["certified_for_trading"] is False and audit["blockers"]


def test_fixed_cost_does_not_disappear_and_passive_benchmarks_avoid_service_cost(tmp_path):
    demo(tmp_path)
    r = compare(tmp_path/"synthetic_daily.csv", fixed_cost_inr=6000)
    assert r["comparison"]["trend"]["fixed_operating_cost"] == "6000.00"
    assert r["comparison"]["cash"]["net_pnl_after_fixed_cost"] == "0.00"
    assert r["comparison"]["buy_hold"]["fixed_operating_cost"] == "0.00"


@settings(max_examples=100, deadline=None)
@given(st.lists(st.integers(10,500), min_size=3, max_size=40))
def test_generated_cash_and_quantity_invariants(prices):
    r = simulate(bars(prices), lookback=2)
    assert all(D(x["cash"]) >= 0 and x["shares"] >= 0 for x in r["equity_curve"])
    assert r["live_orders"] is False


def test_invalid_bars_and_ordering_are_rejected():
    b = bars([100,101,102])
    with pytest.raises(ValueError):
        replace(b[0], close=D("NaN"))
    with pytest.raises(ValueError):
        simulate(list(reversed(b)))


def test_external_trade_import_is_idempotent_and_never_orders(tmp_path):
    p = tmp_path/"trades.csv"
    p.write_text("broker,trade_id,executed_at,isin,exchange,side,quantity,price,fees\nOTHER,T1,2026-11-04T10:00:00+05:30,INE000A00001,NSE,BUY,2,100,1\n")
    import_trades(tmp_path,p); import_trades(tmp_path,p)
    db = Store(tmp_path/"evidence.sqlite3")
    assert db.count() == 1
    db.close()
