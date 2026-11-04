"""Hand-worked numbers from docs/FABLE_SESSION_1_SPEC.md. Each expected value was derived independently of the code."""
import math
from datetime import date, timedelta

import pytest

from marketlab.quant import allocate, forecast, linalg, monitor
from marketlab.quant.allocate import Candidate, Policy, Position


# ---- linear algebra -----------------------------------------------------------------------------------------

def test_ridge_worked_example():
    beta = linalg.ridge([[1, 0], [0, 1], [1, 1], [2, 1]], [1, 2, 3, 5], 1.0)
    assert beta == pytest.approx([26 / 19, 28 / 19], abs=1e-12)


def test_ridge_from_per_date_grams_equals_pooled_fit():
    X1, y1 = [[1.0, 2.0], [1.0, -1.0]], [1.0, 0.5]
    X2, y2 = [[1.0, 0.5], [1.0, 3.0]], [2.0, -1.0]
    G1, g1 = linalg.gram(X1, y1)
    G2, g2 = linalg.gram(X2, y2)
    linalg.add_gram(G1, g1, G2, g2)
    assert linalg.ridge_from_gram(G1, g1, 0.7, unpenalized=(0,)) == pytest.approx(
        linalg.ridge(X1 + X2, y1 + y2, 0.7, unpenalized=(0,)), abs=1e-12)


def test_rank_uniform_midranks_and_spearman():
    assert linalg.rank_uniform([3, 1, 2]) == pytest.approx([(3 - .5) / 3 - .5, (1 - .5) / 3 - .5, (2 - .5) / 3 - .5])
    assert linalg.rank_uniform([1, 1]) == pytest.approx([0.0, 0.0])
    assert linalg.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert linalg.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_shrunk_correlation_is_psd_and_bounded():
    a = [0.01, -0.02, 0.015, 0.0, 0.005, -0.01]
    b = [0.02, -0.01, 0.01, 0.005, 0.0, -0.02]
    c = [-0.01, 0.02, -0.015, 0.01, -0.005, 0.01]
    R = linalg.shrunk_correlation([a, b, c], 0.5)
    assert all(R[i][i] == 1.0 for i in range(3)) and all(-1 <= R[i][j] <= 1 for i in range(3) for j in range(3))
    # Cholesky succeeds only for a positive-definite matrix
    linalg.cholesky_solve(R, [1.0, 1.0, 1.0])


# ---- conformal distribution, shrinkage ---------------------------------------------------------------------

Z = [-2.0, -1.2, -0.7, -0.4, -0.1, 0.2, 0.5, 0.9, 1.4, 2.3]


def test_conformal_quantiles_and_probability_worked_example():
    assert forecast.conformal_index(10, 0.1) == 1 and forecast.conformal_index(10, 0.9) == 10
    mu, sig = 0.01, 0.05
    assert mu + sig * forecast.conformal_z(Z, 0.1) == pytest.approx(-0.09)
    assert mu + sig * forecast.conformal_z(Z, 0.5) == pytest.approx(0.0125)
    assert mu + sig * forecast.conformal_z(Z, 0.9) == pytest.approx(0.125)
    assert forecast.conformal_probability_above(Z, (0 - mu) / sig) == pytest.approx(1 - 5 / 11)


def test_shrinkage_worked_examples():
    assert forecast.shrink(0.015, 0.006) == pytest.approx(0.015 * 0.25 / 0.61)
    assert forecast.shrink(0.03, 0.005) == pytest.approx(0.015)
    assert forecast.shrink(0.03, 0.0) == pytest.approx(0.03)


def test_predict_abstains_without_enough_calibration():
    m = forecast.Model("A.h20.v1", 20, [0.0] * 14, 1.0, forecast.FEATURES, Z, len(Z), 10, date(2026, 1, 1), date(2026, 1, 2),
                       date(2026, 1, 3), date(2026, 1, 4))
    assert forecast.predict(m, {f: 0.0 for f in forecast.FEATURES}, 0.05)["abstain"] == "INSUFFICIENT_CALIBRATION"


# ---- costs, gate, allocation -------------------------------------------------------------------------------

def test_break_even_table():
    assert allocate.break_even(1000) == pytest.approx(0.0176, abs=2e-4)
    assert allocate.break_even(2000) == pytest.approx(0.0099, abs=2e-4)
    assert allocate.break_even(5000) == pytest.approx(0.0053, abs=2e-4)
    assert allocate.break_even(10000) == pytest.approx(0.0038, abs=2e-4)


def test_gate_worked_examples():
    pol = Policy(10_000)
    weak = Candidate("INE000A01001", 100.0, forecast.shrink(0.015, 0.006), 0.06)  # 0.615%: fails at every size
    assert allocate.entry_gate(weak, pol) == (False, ["EDGE_BELOW_COST"])
    strong = Candidate("INE000A01001", 100.0, forecast.shrink(0.03, 0.005), 0.06)  # 1.5%: passes at Rs 5,000
    assert allocate.entry_gate(strong, pol) == (True, [])
    tail = Candidate("INE000A01001", 100.0, 0.015, 0.06, q10=-0.10)
    assert "TAIL_LIMIT" in allocate.entry_gate(tail, pol)[1]
    assert "PRICE_ABOVE_CAP" in allocate.entry_gate(Candidate("INE000A01001", 6000.0, 0.02, 0.06), pol)[1]


CANDS = [Candidate("A", 250.0, 0.012, 0.06), Candidate("B", 1200.0, 0.009, 0.05), Candidate("C", 80.0, 0.004, 0.09)]
CORR = [[1, .3, .3], [.3, 1, .3], [.3, .3, 1]]


def test_allocation_worked_example_exact():
    pol = Policy(10_000, K=3)
    out = allocate.plan(CANDS, CORR, pol, 8_000)
    assert out["quantities"] == {"A": 20} and out["objective"] == pytest.approx(14.5359, abs=1e-3)
    assert out["method"] == "enumeration" and "C" in out["rejected"]
    # adding B at q=2 lowers the objective: Rs 11.46 of expected gain is below the Rs 15.34 fixed charge
    assert allocate.objective([5000, 2400, 0], CANDS, CORR, pol) == pytest.approx(7.0564, abs=1e-3)


def test_neighbourhood_search_matches_enumeration_on_a_small_instance():
    pol = Policy(10_000, K=2)
    exact = allocate.plan(CANDS[:2], CORR, pol, 8_000)
    approx = allocate.plan(CANDS[:2], CORR, pol, 8_000, enumerate_limit=1)
    assert approx["quantities"] == exact["quantities"] and approx["method"].startswith("neighbourhood")


def test_allocation_respects_cash_after_fees_and_count():
    pol = Policy(10_000, K=1, cap_fraction=0.9)
    out = allocate.plan([Candidate("A", 100.0, 0.05, 0.05)], [[1.0]], pol, 3_000)
    assert out["quantities"] == {"A": 29}  # 30 x 100 x (1 + 0.1187%) = 3,003.56 > 3,000
    out = allocate.plan(CANDS, CORR, Policy(10_000, K=1), 8_000)
    assert len(out["quantities"]) == 1


def test_exact_charges_feasibility_is_rechecked():
    # Rs 2,900 buy: STT 2.90 -> Rs 3 (rupee rounding), stamp 0.44, exchange 0.09, GST 0.02: Rs 3.55 of charges
    assert allocate.exact_charges_feasible([29], [Candidate("A", 100.0, 0.05, 0.05)], 2903.55) is True
    assert allocate.exact_charges_feasible([29], [Candidate("A", 100.0, 0.05, 0.05)], 2903.50) is False


def test_exit_policy_worked_example():
    pol = Policy(10_000)
    pos = Position("A", 5000.0, 0.004, 0.06, sessions_held=20)
    alt = [Candidate("B", 100.0, 0.011, 0.06)]
    d = allocate.exit_decision(pos, alt, pol)
    assert d["action"] == "HOLD" and d["u_hold"] == pytest.approx(11.0, abs=1e-3) and d["u_alt"] == pytest.approx(9.536, abs=1e-3)
    assert allocate.exit_decision(Position("A", 5000.0, 0.004, 0.06, sessions_held=5), alt, pol)["reason"] == "WITHIN_HORIZON"
    below = Position("A", 5000.0, -0.01, 0.06, entry_q10=-0.08, realized=-0.09, sessions_held=5)
    d = allocate.exit_decision(below, alt, pol)
    assert "BELOW_ENTRY_Q10" in d["triggers"] and d["action"] == "EXIT"


# ---- monitoring and reliability ---------------------------------------------------------------------------

def test_reliability_worked_example():
    r = monitor.reliability(18, 1)
    assert r["mean"] == pytest.approx(19 / 21) and r["q05"] == pytest.approx(0.7839, abs=2e-4) and r["scored"] is False
    assert monitor.reliability(19, 1)["scored"] is True


def test_cusum_alarms_on_a_downward_shift_only():
    assert monitor.cusum([0.0] * 50)["alarm"] is False
    assert monitor.cusum([-1.0] * 10)["alarm_index"] == 6  # S grows by 0.75 per step: 0.75*7 = 5.25 > 5
    assert monitor.cusum([2.0] * 50)["alarm"] is False


def test_optimal_positions_and_mde_worked_examples():
    F = 15.34 + allocate.VARIABLE_ROUND_TRIP * 2000
    assert monitor.optimal_positions(10_000, 0.06, 0.3, F) == pytest.approx(1.13, abs=0.01)
    assert monitor.optimal_positions(100_000, 0.06, 0.3, F) == pytest.approx(3.57, abs=0.01)
    assert monitor.minimum_detectable_edge(0.06, 512) == pytest.approx(0.00659, abs=2e-5)
    assert monitor.effective_n([(20, 0.2)] * 123) == pytest.approx(512.5, abs=0.1)


def test_calibration_metrics():
    assert monitor.coverage([0, 0, 0], [1, 1, 1], [0.5, 2.0, 0.9]) == pytest.approx(2 / 3)
    assert monitor.brier([1.0, 0.0], [1, 0]) == 0.0
    assert monitor.brier_skill([0.5, 0.5], [1, 0]) == pytest.approx(0.0)
    assert monitor.pit_ks([0.1, 0.5, 0.9]) == pytest.approx(0.2333, abs=1e-3)
