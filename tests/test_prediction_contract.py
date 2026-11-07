from datetime import datetime, timezone

import pytest

from marketlab.quant.prediction import (
    HORIZONS,
    Prediction,
    PredictionStatus,
    Target,
    build_request,
)


def request(target=Target.ABSOLUTE_TOTAL_RETURN, horizon=20):
    return build_request(
        isin="INE000A00001",
        exchange="NSE",
        prediction_time=datetime(2026, 11, 7, 10, tzinfo=timezone.utc),
        horizon_sessions=horizon,
        target=target,
        model_version="ridge.v1",
        calibration_version="conformal.v1",
    )


def available(req=None, **changes):
    values = dict(
        request=req or request(),
        status=PredictionStatus.AVAILABLE,
        data_quality="VERIFIED",
        expected_return=.08,
        median_return=.06,
        q10=-.12,
        q25=-.02,
        q75=.14,
        q90=.25,
        probability_positive=.62,
        probability_negative=.38,
        probability_outperforms_benchmark=.57,
        expected_future_price=108,
        uncertainty=.11,
        reference_price=100,
    )
    values.update(changes)
    return Prediction(**values)


def test_prediction_contract_has_no_execution_inputs():
    fields = set(available().__dataclass_fields__)
    assert not fields.intersection({"capital", "K", "costs", "position_size", "policy", "eligibility"})


def test_absolute_and_relative_predictions_are_distinct_targets():
    assert request().target is Target.ABSOLUTE_TOTAL_RETURN
    assert request(Target.BENCHMARK_RELATIVE_TOTAL_RETURN).target is Target.BENCHMARK_RELATIVE_TOTAL_RETURN


def test_all_required_horizons_are_registered():
    assert HORIZONS == (1, 5, 20, 60, 120, 252)


def test_unavailable_prediction_has_explicit_status():
    p = Prediction.unavailable(request(), PredictionStatus.INSUFFICIENT_HISTORY, "HISTORY_180_SESSIONS")
    assert p.status is PredictionStatus.INSUFFICIENT_HISTORY
    assert p.to_json()["expected_return"] is None


@pytest.mark.parametrize("field,value", [
    ("q25", -.20),
    ("probability_positive", 1.1),
    ("reference_price", 0),
])
def test_invalid_available_forecasts_are_rejected(field, value):
    with pytest.raises(ValueError):
        available(**{field: value})


@pytest.mark.parametrize("horizon", [0, 2, 10, 251])
def test_unregistered_horizons_are_rejected(horizon):
    with pytest.raises(ValueError):
        request(horizon=horizon)


def test_prediction_values_are_invariant_to_downstream_settings():
    baseline = available().to_json()
    downstream_settings = (
        {"capital": 10_000, "K": 1, "costs": "high"},
        {"capital": 1_000_000, "K": 20, "costs": "zero"},
    )
    for settings in downstream_settings:
        assert available().to_json() == baseline
        assert settings
