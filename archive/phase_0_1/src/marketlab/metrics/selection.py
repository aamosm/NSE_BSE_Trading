"""Statistics that discount a backtest for luck and for strategy selection.

- Probabilistic Sharpe ratio (PSR) and minimum track record length: Bailey & Lopez de Prado (2012),
  "The Sharpe Ratio Efficient Frontier".
- Deflated Sharpe ratio (DSR): Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio".
- Probability of backtest overfitting (PBO) by combinatorially symmetric cross-validation (CSCV):
  Bailey, Borwein, Lopez de Prado & Zhu (2017), "The Probability of Backtest Overfitting".

All Sharpe ratios here are PER PERIOD (not annualised), as the formulas require.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist

from .performance import MetricUnavailable, _floats, _mean, _sample_std

EULER_GAMMA = 0.5772156649015329
_N01 = NormalDist()


def _sr_variance_term(sr: float, skew: float, kurtosis: float) -> float:
    v = 1 - skew * sr + (kurtosis - 1) / 4 * sr * sr
    if v <= 0:
        raise MetricUnavailable("non-positive Sharpe-ratio variance term; check skew/kurtosis inputs")
    return v


def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n: int, skew: float, kurtosis: float) -> float:
    """P(true SR > benchmark SR) given an observed per-period SR over n returns.

    PSR = Phi((SR - SR*) * sqrt(n - 1) / sqrt(1 - g3*SR + (g4 - 1)/4 * SR^2)); g4 is non-excess kurtosis.
    """
    if n < 2:
        raise MetricUnavailable("PSR needs n >= 2")
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(_sr_variance_term(sr, skew, kurtosis))
    return _N01.cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum per-period SR among n_trials skill-less trials whose SRs have the given variance.

    E[max] ~= sqrt(V) * ((1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N e))).
    """
    if n_trials < 2:
        raise MetricUnavailable("expected maximum needs at least 2 trials")
    if sr_variance < 0:
        raise MetricUnavailable("variance must be non-negative")
    n = n_trials
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * _N01.inv_cdf(1 - 1 / n)
                                     + EULER_GAMMA * _N01.inv_cdf(1 - 1 / (n * math.e)))


def deflated_sharpe_ratio(sr: float, n: int, skew: float, kurtosis: float, *, n_trials: int,
                          sr_variance_across_trials: float) -> float:
    """PSR against the Sharpe ratio the best of ``n_trials`` skill-less trials would show by chance.

    ``n_trials`` should be the effective number of independent trials actually tried, including
    failed and discarded ones. Under-reporting it inflates the DSR.
    """
    return probabilistic_sharpe_ratio(sr, expected_max_sharpe(n_trials, sr_variance_across_trials), n, skew, kurtosis)


def min_track_record_length(sr: float, sr_benchmark: float, skew: float, kurtosis: float,
                            confidence: float = 0.95) -> float:
    """Observations needed for PSR >= confidence: 1 + V * (z / (SR - SR*))^2."""
    if sr <= sr_benchmark:
        raise MetricUnavailable("observed SR does not exceed the benchmark; no track record suffices")
    z = _N01.inv_cdf(confidence)
    return 1 + _sr_variance_term(sr, skew, kurtosis) * (z / (sr - sr_benchmark)) ** 2


def sharpe_metric(returns: Sequence[float]) -> float:
    """Default CSCV performance metric: per-period mean / sample std (no risk-free adjustment)."""
    sd = _sample_std(returns)
    if sd == 0:
        raise MetricUnavailable("zero variance in a CSCV block")
    return _mean(returns) / sd


@dataclass(frozen=True, slots=True)
class PBOResult:
    pbo: float  # share of IS/OOS splits where the IS-best trial ranks at or below the OOS median
    logits: tuple[float, ...]
    n_splits: int
    n_trials: int


def probability_of_backtest_overfitting(trial_returns: Sequence[Sequence[float]], n_blocks: int,
                                        metric: Callable[[Sequence[float]], float] = sharpe_metric) -> PBOResult:
    """CSCV estimate of PBO.

    ``trial_returns[t][j]`` is the return of trial j in period t (T rows x N columns, same periods
    for every trial). Rows are cut into ``n_blocks`` contiguous equal blocks (T must divide evenly;
    nothing is silently dropped). For every choice of half the blocks as in-sample, the in-sample
    best trial (first on ties) is ranked out-of-sample: rank = number of trials with OOS metric <= its
    OOS metric, w = rank / (N + 1), logit = ln(w / (1 - w)). PBO = share of logits <= 0.
    """
    rows = [_floats(r) for r in trial_returns]
    if n_blocks < 2 or n_blocks % 2:
        raise MetricUnavailable("n_blocks must be an even number >= 2")
    t = len(rows)
    if t == 0 or t % n_blocks:
        raise MetricUnavailable(f"{t} periods do not split into {n_blocks} equal blocks")
    n = len(rows[0])
    if n < 2 or any(len(r) != n for r in rows):
        raise MetricUnavailable("need >= 2 trials and a rectangular matrix")
    size = t // n_blocks
    blocks = [rows[i * size:(i + 1) * size] for i in range(n_blocks)]

    def perf(block_ids: Sequence[int]) -> list[float]:
        sel = [row for b in block_ids for row in blocks[b]]
        return [metric([row[j] for row in sel]) for j in range(n)]

    logits = []
    for is_ids in combinations(range(n_blocks), n_blocks // 2):
        oos_ids = [b for b in range(n_blocks) if b not in is_ids]
        is_perf, oos_perf = perf(is_ids), perf(oos_ids)
        best = max(range(n), key=lambda j: (is_perf[j], -j))
        rank = sum(1 for j in range(n) if oos_perf[j] <= oos_perf[best])
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    pbo = sum(1 for x in logits if x <= 0) / len(logits)
    return PBOResult(pbo, tuple(logits), len(logits), n)
