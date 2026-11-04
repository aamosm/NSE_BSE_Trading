"""Day-level STT/stamp/DP aggregation and coherent decision/submission times (review of 3513d33, 2 and 5)."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest

from marketlab import cli
from marketlab.common import IST
from marketlab.costs import charges as estimate
from marketlab.research import Forecast, paper_proposal
from marketlab.rules import Exchange, InstrumentSnapshot
from marketlab.rules.charges import (
    ZERODHA_2026_11_04 as Z, Fill, TradeKind, day_charges, reconcile_dp,
)
from marketlab.rules.types import Side

DAY = date(2026, 11, 4)
DEL, INTRA, BUY, SELL = TradeKind.DELIVERY, TradeKind.INTRADAY, Side.BUY, Side.SELL


def fill(order, qty, price, kind=DEL, side=SELL, isin="INE000A00001", d=DAY, exchange=Exchange.NSE):
    return Fill(d, exchange, isin, kind, side, D(price), qty, order)


# ---- STT: Zerodha's published worked examples -------------------------------------------------

@pytest.mark.parametrize("fills, stt", [
    ([fill("o1", 500, "105", side=SELL)], D("53")),  # 52.50 -> 53
    ([fill("o1", 500, "100", side=BUY)], D("50")),
    ([fill("o1", 500, "102.50", kind=INTRA, side=SELL)], D("13")),  # 12.8125 -> 13
])
def test_stt_matches_zerodha_worked_examples(fills, stt):
    assert day_charges(Z, fills).stt == stt


def test_stt_is_aggregated_per_security_day_and_side_not_rounded_per_fill():
    # Three delivery sells of 1 share at 400: per fill 0.40 each (would round to 0 each); aggregate 1.20 -> 1.
    fills = [fill("o1", 1, "400"), fill("o2", 1, "400"), fill("o3", 1, "400")]
    r = day_charges(Z, fills)
    assert [g.stt for g in r.stt_groups] == [D("1")] and r.stt == D("1")
    # Same three fills split across two securities are two groups: 0.80 -> 1 and 0.40 -> 0.
    split = [fill("o1", 1, "400"), fill("o2", 1, "400"), fill("o3", 1, "400", isin="INE000B00002")]
    assert sorted(g.stt for g in day_charges(Z, split).stt_groups) == [D("0"), D("1")]


def test_stt_average_price_is_rounded_to_the_paisa_first():
    # 100 @ 100.01 + 200 @ 100.02 = 30,005.00 / 300 = 100.01666 -> 100.02; 0.1% x 100.02 x 300 = 30.006 -> 30
    g = day_charges(Z, [fill("o1", 100, "100.01"), fill("o2", 200, "100.02")]).stt_groups[0]
    assert (g.turnover, g.average_price, g.stt) == (D("30005.00"), D("100.02"), D("30"))


def test_buy_and_sell_sides_are_separate_groups():
    r = day_charges(Z, [fill("b", 500, "100", side=BUY), fill("s", 500, "105", side=SELL)])
    assert r.stt == D("50") + D("53")


def test_dp_once_per_security_per_sell_day_delivery_only():
    r = day_charges(Z, [fill("o1", 1, "400"), fill("o2", 5, "401")])
    assert r.dp == D("15.34")
    two = day_charges(Z, [fill("o1", 1, "400"), fill("o2", 1, "50", isin="INE000B00002")])
    assert two.dp == D("30.68")
    intraday = day_charges(Z, [fill("o1", 1, "400", kind=INTRA)])
    assert intraday.dp == 0


def test_brokerage_cap_applies_per_executed_order_and_totals_add_up():
    # Two intraday orders of 1,000 x 100 = 1,00,000 each: 0.03% = 30 -> capped at 20 per order.
    r = day_charges(Z, [fill("o1", 1000, "100", kind=INTRA, side=BUY), fill("o2", 1000, "100", kind=INTRA, side=BUY)])
    assert [c.brokerage for _, c in r.orders] == [D("20.00"), D("20.00")]
    assert r.total == r.non_stt + r.stt + r.dp
    assert "STAMP_ALLOCATION_UNRESOLVED" in r.assumptions and "STT_AGGREGATION_UNRECONCILED" in r.assumptions


def test_order_cannot_mix_sides():
    with pytest.raises(ValueError, match="mixes"):
        day_charges(Z, [fill("o1", 1, "10", side=BUY), fill("o1", 1, "10", side=SELL)])


def test_single_order_estimate_uses_rupee_stt():
    assert estimate(52500, side="SELL", style="delivery")["stt"] == D("53")
    assert estimate(1000, side="SELL", style="intraday")["stt"] == D("0")


def test_dp_reconciliation_reports_differences_without_adjusting():
    expected = {date(2026, 11, 4): D("15.34"), date(2026, 11, 5): D("30.68")}
    ok = reconcile_dp(expected, dict(expected))
    assert ok["matched"] is True
    bad = reconcile_dp(expected, {date(2026, 11, 4): D("15.05")})
    assert bad["matched"] is False
    assert [r["difference"] for r in bad["rows"]] == [D("-0.29"), D("-30.68")]


# ---- Decision and submission time --------------------------------------------------------------

T = datetime(2026, 11, 4, 10, tzinfo=IST)


def forecast(**kw):
    f = Forecast("INE000A00001", "NSE", "TEST", "swing", T, T + timedelta(hours=1), 20, .10, -.05, .08, .20,
                 .01, .65, 200, "m", "c", ("e1",), True)
    return replace(f, **kw)


def snapshot(**kw):
    s = InstrumentSnapshot(as_of=T.date(), exchange=Exchange.NSE, symbol="TESTA", isin="INE000A00001", series="EQ",
                           has_derivatives=False, base_price=D("100.00"), price_band_pct=D("20"),
                           tick_reference_price=D("100.00"), ltp=D("100.00"), surveillance=frozenset(),
                           in_periodic_call_auction=False, suspended=False, special_preopen_today=False,
                           mis_eligible=True, snapshot_id="S")
    return replace(s, **kw)


def propose(f=None, **kw):
    args = dict(at=T, price=100, equity=10000, available_cash=10000, known_status=True, restricted=False,
                spread_bps=5, median_daily_volume=100000, status_as_of=T, quote_as_of=T, snapshot=snapshot())
    args.update(kw)
    return paper_proposal(f or forecast(), **args)


def test_prompt_submission_is_accepted():
    assert propose(submit_at=T + timedelta(seconds=60))["action"] == "PAPER_BUY_PROPOSAL"


@pytest.mark.parametrize("kw, reason", [
    ({"submit_at": T + timedelta(minutes=3)}, "REVALIDATION_REQUIRED"),
    ({"submit_at": T - timedelta(seconds=1)}, "SUBMISSION_BEFORE_DECISION"),
    ({"quote_as_of": T + timedelta(seconds=30), "submit_at": T + timedelta(minutes=1)}, "STALE_OR_MISSING_MARKET_INPUT"),
    ({"quote_as_of": T - timedelta(minutes=4, seconds=30), "submit_at": T + timedelta(minutes=1)},
     "STALE_OR_MISSING_MARKET_INPUT"),
])
def test_decision_and_submission_must_be_coherent(kw, reason):
    p = propose(**kw)
    assert p["action"] == "ABSTAIN" and reason in p["reasons"]


def test_forecast_expiring_before_submission_abstains():
    p = propose(forecast(expires_at=T + timedelta(seconds=30)), submit_at=T + timedelta(seconds=60))
    assert "STALE_OR_FUTURE_FORECAST" in p["reasons"]


def test_bse_fee_group_comes_from_the_snapshot_not_the_caller():
    with pytest.raises(TypeError):
        propose(bse_group="A")  # the override argument no longer exists
    unknown = propose(forecast(exchange="BSE"), snapshot=snapshot(exchange=Exchange.BSE, series="EQ"))
    assert "BSE_FEE_GROUP_UNKNOWN" in unknown["reasons"]
    known = propose(forecast(exchange="BSE"), snapshot=snapshot(exchange=Exchange.BSE, series="A"))
    assert "BSE_FEE_GROUP_UNKNOWN" not in known["reasons"]  # still abstains: BSE calendar not loaded
    assert known["action"] == "ABSTAIN" and "SESSION_UNKNOWN" in known["rule_codes"]


def test_bse_backtest_needs_the_group_from_dataset_metadata(tmp_path):
    data = tmp_path / "x.csv"
    data.write_text("start\n")
    with pytest.raises(ValueError, match="security master"):
        cli.dataset_bse_group(data)
    data.with_suffix(".metadata.json").write_text(json.dumps({"bse_group": "A", "bse_group_source": "BSE bhavcopy"}))
    assert cli.dataset_bse_group(data) == "A"
