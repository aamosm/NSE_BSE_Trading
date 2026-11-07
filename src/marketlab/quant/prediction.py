"""Prediction-only contracts for MarketLab's model layer.

This module deliberately has no imports from allocation, execution, account,
broker, or cost modules. A prediction describes a stock and a target at a
point in time; it does not describe whether the stock may be traded.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

HORIZONS = (1, 5, 20, 60, 120, 252)
ISIN_RE = re.compile(r"INE[A-Z0-9]{9}")


class Target(StrEnum):
    ABSOLUTE_TOTAL_RETURN = "absolute_total_return"
    BENCHMARK_RELATIVE_TOTAL_RETURN = "benchmark_relative_total_return"


class PredictionStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MISSING_FEATURES = "MISSING_FEATURES"
    UNRESOLVED_LABEL = "UNRESOLVED_LABEL"
    DATA_QUALITY_UNKNOWN = "DATA_QUALITY_UNKNOWN"


@dataclass(frozen=True, slots=True)
class PredictionRequest:
    """The complete model input; execution and account state are absent by design."""

    isin: str
    exchange: str
    prediction_time: datetime
    horizon_sessions: int
    target: Target
    model_version: str
    calibration_version: str

    def __post_init__(self) -> None:
        if not ISIN_RE.fullmatch(self.isin):
            raise ValueError("A valid equity ISIN is required")
        if self.exchange not in {"NSE", "BSE"}:
            raise ValueError("Only NSE and BSE equities are supported")
        if self.prediction_time.tzinfo is None:
            raise ValueError("prediction_time must be timezone-aware")
        if self.horizon_sessions not in HORIZONS:
            raise ValueError(f"horizon_sessions must be one of {HORIZONS}")
        if not self.model_version.strip() or not self.calibration_version.strip():
            raise ValueError("Model and calibration versions are required")


@dataclass(frozen=True, slots=True)
class Prediction:
    """A quantity-independent probabilistic forecast for one stock and horizon."""

    request: PredictionRequest
    status: PredictionStatus
    data_quality: str
    expected_return: float | None = None
    median_return: float | None = None
    q10: float | None = None
    q25: float | None = None
    q75: float | None = None
    q90: float | None = None
    probability_positive: float | None = None
    probability_negative: float | None = None
    probability_outperforms_benchmark: float | None = None
    expected_future_price: float | None = None
    uncertainty: float | None = None
    reference_price: float | None = None

    def __post_init__(self) -> None:
        values = (self.expected_return, self.median_return, self.q10, self.q25,
                  self.q75, self.q90, self.probability_positive,
                  self.probability_negative, self.probability_outperforms_benchmark,
                  self.expected_future_price, self.uncertainty, self.reference_price)
        if self.status is PredictionStatus.AVAILABLE:
            if any(v is None or not math.isfinite(v) for v in values):
                raise ValueError("Available predictions require finite forecast values")
            if not self.q10 <= self.q25 <= self.median_return <= self.q75 <= self.q90:
                raise ValueError("Prediction quantiles must be ordered")
            probabilities = (self.probability_positive, self.probability_negative,
                             self.probability_outperforms_benchmark)
            if any(not 0 <= p <= 1 for p in probabilities):
                raise ValueError("Prediction probabilities must be in [0, 1]")
            if self.uncertainty < 0 or self.reference_price <= 0 or self.expected_future_price <= 0:
                raise ValueError("Prediction scale values are invalid")
        elif any(v is not None for v in values):
            raise ValueError("Unavailable predictions must not contain forecast values")

    @classmethod
    def unavailable(cls, request: PredictionRequest, status: PredictionStatus,
                    data_quality: str) -> "Prediction":
        if status is PredictionStatus.AVAILABLE:
            raise ValueError("Use the full constructor for an available prediction")
        return cls(request=request, status=status, data_quality=data_quality)

    def to_json(self) -> dict:
        return {
            "isin": self.request.isin,
            "exchange": self.request.exchange,
            "prediction_time": self.request.prediction_time.isoformat(),
            "horizon_sessions": self.request.horizon_sessions,
            "target": self.request.target.value,
            "model_version": self.request.model_version,
            "calibration_version": self.request.calibration_version,
            "status": self.status.value,
            "data_quality": self.data_quality,
            "expected_return": self.expected_return,
            "median_return": self.median_return,
            "q10": self.q10,
            "q25": self.q25,
            "q75": self.q75,
            "q90": self.q90,
            "probability_positive": self.probability_positive,
            "probability_negative": self.probability_negative,
            "probability_outperforms_benchmark": self.probability_outperforms_benchmark,
            "expected_future_price": self.expected_future_price,
            "uncertainty": self.uncertainty,
            "reference_price": self.reference_price,
        }


def build_request(*, isin: str, exchange: str, prediction_time: datetime,
                  horizon_sessions: int, target: Target, model_version: str,
                  calibration_version: str) -> PredictionRequest:
    """Construct a prediction request without accepting downstream settings."""
    return PredictionRequest(isin, exchange, prediction_time, horizon_sessions, target,
                             model_version, calibration_version)
