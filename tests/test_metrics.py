"""Metrics against hand-worked values (derivations in comments; see docs/METRICS.md)."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from marketlab.metrics import (
    Drawdown,
    MetricUnavailable,
    RoundTrip,
    annualized_return,
    beta,
    cagr,
    calmar_ratio,
    compound_return,
    cost_bps_of_turnover,
    deflated_sharpe_ratio,
    downside_deviation,
    expected_max_sharpe,
    expected_shortfall,
    historical_var,
    information_ratio,
    max_drawdown,
    min_track_record_length,
    moments,
    per_period_rate,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    round_trip_breakeven,
    sharpe_ratio,
    simple_returns,
    slippage_bps,
    sortino_ratio,
    time_weighted_returns,
    tracking_error,
    trade_stats,
    trading_sessions_in_year,
    turnover_ratio,
    ulcer_index,
    volatility,
    xirr,
)
from marketlab.rules import Exchange, MarketCalendar, RuleUnknown, Side
from marketlab.rules.charges import ZERODHA_2026_11_04, TradeKind

APPROX = dict(rel=1e-9, abs=1e-12)


# ---------------------------------------------------------------- annualisation

def test_nse_2026_has_246_sessions_not_252():
    # 2026 starts on a Thursday: 52 weeks + 1 weekday = 261 weekdays; 16 weekday trading holidays;
    # plus the full Budget Sunday session on 1 Feb 2026 (NSE/CMTR/72349) = 246. Muhurat is excluded.
    assert trading_sessions_in_year(MarketCalendar(), Exchange.NSE, 2026) == 246


def test_unloaded_year_cannot_be_annualised():
    with pytest.raises(RuleUnknown):
        trading_sessions_in_year(MarketCalendar(), Exchange.NSE, 2027)


# ---------------------------------------------------------------- returns

def test_deposits_are_not_returns():
    # Day 2: Rs 50 deposited before trading, value ends 160 = 110 + 50 -> 0% return.
    # Day 3: Rs 10 withdrawn, value ends 150 = 160 - 10 -> 0%. Only day 1 earned 10%.
    r = time_weighted_returns([100, 110, 160, 150], [0, 0, 50, -10])
    assert r == pytest.approx([0.10, 0.0, 0.0], **APPROX)
    assert compound_return(r) == pytest.approx(0.10, **APPROX)
    naive = compound_return(simple_returns([100, 110, 160, 150]))
    assert naive == pytest.approx(0.50, **APPROX)  # what a flow-blind metric would report


def test_twr_rejects_opening_flow_and_length_mismatch():
    with pytest.raises(MetricUnavailable):
        time_weighted_returns([100, 110], [5, 0])
    with pytest.raises(MetricUnavailable):
        time_weighted_returns([100, 110], [0])


def test_annualized_return_and_cagr_and_period_rate():
    assert annualized_return([0.1, 0.1], periods_per_year=1) == pytest.approx(0.1, **APPROX)
    # 2020-01-01 -> 2024-01-01 is 1461 days = 4.0 years at ACT/365.25; 1.1^4 = 1.4641.
    assert cagr(100, D("146.41"), date(2020, 1, 1), date(2024, 1, 1)) == pytest.approx(0.1, rel=1e-12)
    assert per_period_rate(0.21, 2) == pytest.approx(0.1, **APPROX)


def test_xirr_single_and_multiple_flows():
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-9)
    # 1000 x 1.1^2 + 1000 x 1.1 = 2310 two years after the first deposit.
    flows = [(date(2025, 1, 1), -1000), (date(2026, 1, 1), -1000), (date(2027, 1, 1), 2310)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)
    with pytest.raises(MetricUnavailable):
        xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), -5)])


# ---------------------------------------------------------------- dispersion and ratios
# r = [1%, 2%, -1%, 0%]: mean 0.005; squared deviations sum to 5e-4; sample variance 5e-4/3.

R4 = [0.01, 0.02, -0.01, 0.00]


def test_volatility_sample_std():
    assert volatility(R4, 240) == pytest.approx(0.2, **APPROX)  # sqrt(5e-4/3 x 240) = sqrt(0.04)


def test_sharpe_exact_values_and_rf_is_mandatory():
    # per-period SR^2 = 0.005^2 / (5e-4/3) = 0.15; x 240 sessions -> 36 -> 6.
    assert sharpe_ratio(R4, rf_per_period=0.0, periods_per_year=240) == pytest.approx(6.0, **APPROX)
    # rf 0.1%/period: excess mean 0.004 -> SR^2 = 0.000016 x 3 / 5e-4 x 240 = 23.04 -> 4.8.
    assert sharpe_ratio(R4, rf_per_period=0.001, periods_per_year=240) == pytest.approx(4.8, **APPROX)
    with pytest.raises(TypeError):
        sharpe_ratio(R4, periods_per_year=240)  # type: ignore[call-arg]
    with pytest.raises(MetricUnavailable):
        sharpe_ratio([0.01, 0.01, 0.01], rf_per_period=0, periods_per_year=245)


def test_sortino_counts_all_periods_in_downside_deviation():
    r = [0.02, -0.01, 0.03, -0.02]  # downside squares 1e-4 + 4e-4 over n = 4 -> 1.25e-4
    assert downside_deviation(r, 0.0, 5) == pytest.approx(0.025, **APPROX)
    assert sortino_ratio(r, mar_per_period=0.0, periods_per_year=5) == pytest.approx(1.0, **APPROX)
    with pytest.raises(MetricUnavailable):
        sortino_ratio([0.01, 0.02], mar_per_period=0.0, periods_per_year=5)


def test_moments_population_convention():
    skew, kurt = moments([-1, 0, 1])
    assert skew == pytest.approx(0.0, abs=1e-15) and kurt == pytest.approx(1.5, **APPROX)
    # [0, 0, 3]: m2 = 2, m3 = 2, m4 = 6 -> skew 1/sqrt(2), kurtosis 1.5
    skew, kurt = moments([0, 0, 3])
    assert skew == pytest.approx(1 / math.sqrt(2), **APPROX) and kurt == pytest.approx(1.5, **APPROX)


def test_benchmark_relative_metrics():
    b = [0.01, -0.02, 0.03]
    assert beta([2 * x for x in b], b) == pytest.approx(2.0, **APPROX)
    r = [x + a for x, a in zip(b, [0.001, 0.003, 0.002])]  # active mean 0.002, sample sd 0.001
    assert tracking_error(r, b, 4) == pytest.approx(0.002, rel=1e-9)
    assert information_ratio(r, b, 4) == pytest.approx(4.0, rel=1e-9)


def test_tail_risk_without_interpolation():
    r = [-0.05, -0.03] + [0.01] * 18
    assert historical_var(r, 0.95) == pytest.approx(0.05) and expected_shortfall(r, 0.95) == pytest.approx(0.05)
    assert historical_var(r, 0.90) == pytest.approx(0.03) and expected_shortfall(r, 0.90) == pytest.approx(0.04)


# ---------------------------------------------------------------- drawdowns

def test_max_drawdown_depth_dates_and_recovery():
    dd = max_drawdown([100, 120, 90, 95, 130, 117])
    assert dd == Drawdown(0.25, peak_index=1, trough_index=2, recovery_index=4)
    assert dd.decline_periods == 1 and dd.underwater_periods == 3
    # drawdowns 0, 0, -0.25, -5/24, 0, -0.1 -> sqrt(0.11590278 / 6)
    assert ulcer_index([100, 120, 90, 95, 130, 117]) == pytest.approx(0.1389861, abs=1e-7)
    assert calmar_ratio(0.10, dd) == pytest.approx(0.4)


def test_unrecovered_and_flat_drawdowns():
    dd = max_drawdown([100, 80, 90])
    assert dd.depth == pytest.approx(0.2) and dd.recovery_index is None and dd.underwater_periods is None
    assert max_drawdown([100, 100, 101]).depth == 0
    with pytest.raises(MetricUnavailable):
        calmar_ratio(0.1, max_drawdown([100, 101]))


@given(st.lists(st.floats(min_value=1, max_value=1e6, allow_nan=False), min_size=1, max_size=60))
def test_drawdown_bounds_property(values):
    dd = max_drawdown(values)
    assert 0 <= dd.depth < 1
    assert dd.peak_index <= dd.trough_index
    if dd.depth > 0:
        assert values[dd.trough_index] == pytest.approx(values[dd.peak_index] * (1 - dd.depth), rel=1e-9)


# ---------------------------------------------------------------- selection bias

def test_psr_hand_value_and_symmetry():
    # z = 0.1 x sqrt(100) / sqrt(1 + 0.5 x 0.01) = 0.99750934; Phi(z) = 0.8407417 (table + linear step)
    assert probabilistic_sharpe_ratio(0.1, 0.0, 101, 0.0, 3.0) == pytest.approx(0.8407417, abs=2e-6)
    assert probabilistic_sharpe_ratio(0.1, 0.1, 50, 0.0, 3.0) == pytest.approx(0.5, **APPROX)
    # negative skew widens the SR error, so the same SR is less convincing
    assert probabilistic_sharpe_ratio(0.1, 0.0, 101, -1.0, 3.0) < probabilistic_sharpe_ratio(0.1, 0.0, 101, 0.0, 3.0)


def test_expected_max_sharpe_and_dsr():
    # (1-g) x Phi^-1(0.9) + g x Phi^-1(1 - 1/(10e)) = 0.4227843 x 1.2815516 + 0.5772157 x 1.789242
    assert expected_max_sharpe(10, 1.0) == pytest.approx(1.574600, abs=1e-4)
    assert expected_max_sharpe(10, 4.0) == pytest.approx(2 * expected_max_sharpe(10, 1.0), **APPROX)
    # SR0 = 0.04 x 1.5746 = 0.062984; z = (0.1 - 0.062984) x 10 / 1.0024969 = 0.369238 -> 0.64403
    dsr = deflated_sharpe_ratio(0.1, 101, 0.0, 3.0, n_trials=10, sr_variance_across_trials=0.0016)
    assert dsr == pytest.approx(0.64403, abs=2e-4)
    assert dsr < probabilistic_sharpe_ratio(0.1, 0.0, 101, 0.0, 3.0)
    with pytest.raises(MetricUnavailable):
        expected_max_sharpe(1, 1.0)


def test_min_track_record_length():
    # 1 + 1.005 x (1.6448536 / 0.1)^2 = 1 + 1.005 x 270.55434 = 272.907
    assert min_track_record_length(0.1, 0.0, 0.0, 3.0, 0.95) == pytest.approx(272.907, abs=1e-2)
    with pytest.raises(MetricUnavailable):
        min_track_record_length(0.0, 0.1, 0.0, 3.0)


def test_pbo_is_one_when_in_sample_winner_always_loses_out_of_sample():
    # columns = trials A, B. Block 0: A strong, B flat. Block 1: reversed.
    m = [[0.02, 0.01], [0.04, -0.01], [0.01, 0.02], [-0.01, 0.04]]
    res = probability_of_backtest_overfitting(m, n_blocks=2)
    assert res.n_splits == 2 and res.pbo == 1.0
    assert res.logits == pytest.approx((math.log(0.5), math.log(0.5)))


def test_pbo_is_zero_for_a_dominant_trial():
    m = [[0.02, 0.01], [0.04, -0.01], [0.03, 0.00], [0.05, 0.01]]
    res = probability_of_backtest_overfitting(m, n_blocks=2)
    assert res.pbo == 0.0 and res.logits == pytest.approx((math.log(2), math.log(2)))


def test_pbo_rejects_uneven_or_odd_blocks():
    m = [[0.01, 0.02]] * 5
    with pytest.raises(MetricUnavailable):
        probability_of_backtest_overfitting(m, n_blocks=2)
    with pytest.raises(MetricUnavailable):
        probability_of_backtest_overfitting([[0.01, 0.02]] * 6, n_blocks=3)


# ---------------------------------------------------------------- trades and costs

def _rt(entry, exit_, charges, interest="0", sessions=0, product="CNC"):
    return RoundTrip("INE000X00010", product, date(2026, 11, 2), date(2026, 11, 4), 10, D(entry), D(exit_),
                     D(charges), D(interest), sessions)


def test_trade_stats_on_net_pnl():
    trips = [_rt("1000", "1100", "20", sessions=5),                 # net +80
             _rt("1000", "950", "18", sessions=3),                  # net -68
             _rt("2000", "2040", "42", "0", 10),                    # gross +40 but net -2 after costs
             _rt("500", "560", "10", sessions=2)]                   # net +50
    s = trade_stats(trips)
    assert (s.count, s.wins, s.losses, s.flat) == (4, 2, 2, 0)
    assert s.win_rate == 0.5
    assert (s.gross_pnl, s.charges, s.interest, s.net_pnl) == (D("150"), D("90"), D("0"), D("60"))
    assert (s.average_win, s.average_loss, s.expectancy) == (D("65.00"), D("-35.00"), D("15.00"))
    assert s.payoff_ratio == pytest.approx(65 / 35) and s.profit_factor == pytest.approx(130 / 70)
    assert s.cost_share_of_gross == pytest.approx(0.6) and s.average_sessions_held == 5.0
    with pytest.raises(MetricUnavailable):
        trade_stats([])


def test_turnover_cost_and_slippage():
    assert turnover_ratio(D("40000"), D("10000")) == 2.0
    assert cost_bps_of_turnover(D("12"), D("40000")) == pytest.approx(3.0)
    assert slippage_bps(Side.BUY, D("100"), D("100.10")) == pytest.approx(10.0)
    assert slippage_bps(Side.SELL, D("100"), D("99.95")) == pytest.approx(5.0)
    assert slippage_bps(Side.SELL, D("100"), D("100.05")) == pytest.approx(-5.0)


def test_breakeven_small_delivery_trade_is_dominated_by_dp_charge():
    # Rs 1,000 delivery: buy = STT 1.00 + txn 0.03 + stamp 0.15 + GST 0.01 = 1.19; DP 15.34.
    # Sell near 101.76: STT 1.02 + txn 0.03 + GST 0.01 = 1.06. Need 10 x move >= 17.59 -> 101.76.
    be = round_trip_breakeven(ZERODHA_2026_11_04, exchange=Exchange.NSE, kind=TradeKind.DELIVERY,
                              price=D("100"), quantity=10, trade_date=date(2026, 11, 4))
    assert (be.buy_charges, be.dp_charge, be.sell_charges) == (D("1.19"), D("15.34"), D("1.06"))
    assert be.exit_price == D("101.76") and be.move_pct == D("1.7600")


def test_breakeven_ten_thousand_delivery_trade():
    # buy 11.88 (STT 10, txn 0.31, SEBI 0.01, stamp 1.50, GST 0.06); sell at 1003.77: 10.42; DP 15.34
    be = round_trip_breakeven(ZERODHA_2026_11_04, exchange=Exchange.NSE, kind=TradeKind.DELIVERY,
                              price=D("1000"), quantity=10, trade_date=date(2026, 11, 4))
    assert (be.buy_charges, be.sell_charges) == (D("11.88"), D("10.42"))
    assert be.exit_price == D("1003.77") and be.move_pct == D("0.3770")


def test_r09_pbo_midranks_ties_instead_of_ranking_them_as_wins():
    # Review counterexample: 2 blocks x 3 trials scored by mean. Split A: IS block 0 picks trial 0;
    # OOS block 1 is all tied at 0.01 -> midrank 2 -> w = 2/4 -> logit 0 -> counts as overfit.
    # Split B: IS block 1 is all tied -> first trial; OOS block 0 ranks it 3 -> w = 3/4 -> logit > 0.
    m = [[0.03, 0.02, 0.01], [0.03, 0.02, 0.01], [0.01, 0.01, 0.01], [0.01, 0.01, 0.01]]
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    res = probability_of_backtest_overfitting(m, n_blocks=2, metric=mean)
    assert res.pbo == 0.5
    assert sorted(res.logits) == pytest.approx([0.0, math.log(3)])
