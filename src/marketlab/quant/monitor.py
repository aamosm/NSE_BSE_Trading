"""Decay monitoring (spec section 7) and source-reliability updates (spec section 9)."""
from __future__ import annotations

import math


def cusum(errors: list[float], k: float = 0.25, h: float = 5.0) -> dict:
    """One-sided CUSUM on standardized forecast errors e_t = (y - mu)/sigma, detecting a downward mean shift:
    S_t = max(0, S_{t-1} - e_t - k). Alarm when S_t > h."""
    s, path, alarm_at = 0.0, [], None
    for i, e in enumerate(errors):
        s = max(0.0, s - e - k)
        path.append(s)
        if alarm_at is None and s > h:
            alarm_at = i
    return {"statistic": s, "alarm": alarm_at is not None, "alarm_index": alarm_at, "path": path}


def pit_ks(pits: list[float]) -> float:
    """Kolmogorov-Smirnov distance of probability-integral transforms from Uniform(0, 1)."""
    n = len(pits)
    if n == 0:
        return float("nan")
    s = sorted(pits)
    d = 0.0
    for i, u in enumerate(s):
        d = max(d, abs((i + 1) / n - u), abs(u - i / n))
    return d


def coverage(lower: list[float], upper: list[float], y: list[float]) -> float:
    inside = sum(1 for lo, hi, v in zip(lower, upper, y) if lo <= v <= hi)
    return inside / len(y) if y else float("nan")


def brier(p: list[float], y: list[int]) -> float:
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y) if y else float("nan")


def brier_skill(p: list[float], y: list[int]) -> float:
    """1 - Brier / Brier(climatology), climatology = the realized base rate."""
    if not y:
        return float("nan")
    base = sum(y) / len(y)
    ref = sum((base - yi) ** 2 for yi in y) / len(y)
    return 1 - brier(p, y) / ref if ref > 0 else float("nan")


def effective_n(blocks: list[tuple[int, float]]) -> float:
    """N_eff = sum_b m_b / (1 + (m_b - 1) rho_b) over date blocks (m trades, within-block correlation rho)."""
    return sum(m / (1 + (m - 1) * max(0.0, rho)) for m, rho in blocks if m > 0)


def minimum_detectable_edge(sigma: float, n_eff: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """One-sided test: mu_min = (z_alpha + z_beta) sigma / sqrt(n_eff)."""
    from statistics import NormalDist
    nd = NormalDist()
    return (nd.inv_cdf(1 - alpha) + nd.inv_cdf(power)) * sigma / math.sqrt(n_eff)


def optimal_positions(W: float, sigma: float, rho: float, fixed_cost: float, turnover: float = 1.0, gamma: float | None = None) -> float:
    """n* = W sigma sqrt(gamma (1 - rho) / (2 F tau)); with gamma = 2/W this is sigma sqrt(W (1 - rho) / (F tau))."""
    g = gamma if gamma is not None else 2.0 / W
    return W * sigma * math.sqrt(g * (1 - rho) / (2 * fixed_cost * turnover))


def reliability(correct: int, wrong: int, alpha0: float = 1.0, beta0: float = 1.0, q: float = 0.05) -> dict:
    """Beta(alpha0 + c, beta0 + w): mean and the q-quantile (bisection on the regularized incomplete beta)."""
    a, b = alpha0 + correct, beta0 + wrong
    mean = a / (a + b)
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return {"mean": mean, "q05": lo, "scored": correct + wrong >= 20}


def _beta_cdf(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b) by continued fraction (Numerical Recipes betacf)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(x, a, b) / a
    return 1 - front * _betacf(1 - x, b, a) / b


def _betacf(x, a, b, max_iter=300, eps=1e-14):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / d if abs(d) > 1e-300 else 1e300
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-300 else 1e300
        c = 1 + aa / c if abs(c) > 1e-300 else 1e300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / d if abs(d) > 1e-300 else 1e300
        c = 1 + aa / c if abs(c) > 1e-300 else 1e300
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            break
    return h
