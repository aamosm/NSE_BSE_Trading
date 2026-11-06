"""Cross-sectional ridge with split-conformal, vol-scaled predictive distributions (spec section 4)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date

from .features import FEATURES, MARKET_FEATURES, design_vector
from .linalg import add_gram, dot, gram, ridge_from_gram, zeros

MIN_CALIBRATION = 200
LAM_GRID = (1.0, 10.0, 100.0)  # multiplied by n/1000 (spec section 4.2)
TAU_DEFAULT = 0.005  # prior scale of true 20-session edges (spec section 4.4)
# Design-vector positions of the common part: the intercept and the market features take the same value for every
# stock on a date, so together they are a market-timing forecast (the universe against the Nifty 50).
COMMON_IDX = (0,) + tuple(1 + FEATURES.index(f) for f in MARKET_FEATURES)


@dataclass
class Model:
    target_id: str
    h: int
    beta: list[float]
    lam: float
    feature_names: tuple[str, ...]
    z_sorted: list[float]  # standardized calibration residuals, ascending
    calibration_n: int
    n_train: int
    train_start: date
    train_end: date
    calibration_start: date
    calibration_end: date
    inner_scores: dict = field(default_factory=dict)
    bootstrap_betas: list[list[float]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"target_id": self.target_id, "h": self.h, "beta": self.beta, "lam": self.lam,
                "features": list(self.feature_names), "calibration_n": self.calibration_n, "n_train": self.n_train,
                "train": [self.train_start.isoformat(), self.train_end.isoformat()],
                "calibration": [self.calibration_start.isoformat(), self.calibration_end.isoformat()],
                "inner_scores": self.inner_scores, "z_quantiles": {p: conformal_z(self.z_sorted, p) for p in (0.1, 0.5, 0.9)}
                if self.z_sorted else {}, "bootstraps": len(self.bootstrap_betas)}


def conformal_index(n: int, alpha: float) -> int:
    """1-based order statistic used for the alpha quantile: floor((n+1)alpha) for the lower tail,
    ceil((n+1)alpha) for the upper tail (alpha > 0.5); clipped to [1, n]."""
    k = math.floor((n + 1) * alpha) if alpha <= 0.5 else math.ceil((n + 1) * alpha)
    return min(max(k, 1), n)


def conformal_z(z_sorted: list[float], alpha: float) -> float:
    n = len(z_sorted)
    if alpha == 0.5:
        return z_sorted[n // 2] if n % 2 else (z_sorted[n // 2 - 1] + z_sorted[n // 2]) / 2
    return z_sorted[conformal_index(n, alpha) - 1]


def conformal_probability_above(z_sorted: list[float], c: float) -> float:
    """P(y > threshold) = 1 - (#{z <= c} + 1)/(n + 1), c the standardized threshold (conservative)."""
    n = len(z_sorted)
    k = 0
    for z in z_sorted:
        if z <= c:
            k += 1
        else:
            break
    return 1 - (k + 1) / (n + 1)


def shrink(mu_hat: float, se: float, tau: float = TAU_DEFAULT) -> float:
    """Empirical-Bayes shrinkage toward 0: mu * tau^2 / (tau^2 + se^2). 1.5%, 0.6% -> 0.6148%."""
    return mu_hat * tau * tau / (tau * tau + se * se)


def _sd(v: list[float]) -> float:
    m = sum(v) / len(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


def pinball(y: float, q: float, tau: float) -> float:
    return (tau - (1.0 if y < q else 0.0)) * (y - q)


def _gram_by_date(rows, y_key="y"):
    """{day: (G, g, n)} with the intercept as column 0."""
    by_day: dict[date, list] = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    out = {}
    for d, rs in by_day.items():
        X = [design_vector(r["x"]) for r in rs]
        y = [r[y_key] for r in rs]
        G, g = gram(X, y)
        out[d] = (G, g, len(rs))
    return out


def _fit_from_dates(grams, days, lam):
    k = len(FEATURES) + 1
    G, g = zeros(k, k), [0.0] * k
    n = 0
    for d in days:
        Gd, gd, nd = grams[d]
        add_gram(G, g, Gd, gd)
        n += nd
    if n == 0:
        raise ValueError("no training rows")
    return ridge_from_gram(G, g, lam * n / 1000.0, unpenalized=(0,)), n


def fit(rows: list[dict], *, h: int, target_id: str, lam_grid=LAM_GRID, inner_fraction=0.2, purge_sessions: int | None = None,
        sessions: list[date] | None = None, bootstrap: int = 0, seed: int = 0) -> Model:
    """Fit on the first (1 - inner_fraction) of training dates; choose lambda and collect conformal residuals on the
    purged last part. ``rows``: dicts with day, isin, x (standardized features), y, sigma (vol_20 * sqrt(h))."""
    days = sorted({r["day"] for r in rows})
    if len(days) < 10:
        raise ValueError("too few training dates")
    purge = purge_sessions if purge_sessions is not None else h + 1
    split = int(len(days) * (1 - inner_fraction))
    cal_days = days[split:]
    if sessions:  # purge by session index: a fit row's label ends at decision + h + 1, which must precede the calibration start
        idx = {d: i for i, d in enumerate(sessions)}
        first_cal = idx[cal_days[0]]
        fit_days = [d for d in days[:split] if idx[d] + purge < first_cal]
    else:
        fit_days = days[:max(1, split - purge)]
    if not fit_days:
        raise ValueError("purging left no fit dates")
    grams = _gram_by_date(rows)
    cal_rows = [r for r in rows if r["day"] in set(cal_days)]
    scores, betas = {}, {}
    for lam in lam_grid:
        beta, _ = _fit_from_dates(grams, fit_days, lam)
        betas[lam] = beta
        mse = pin = 0.0
        for r in cal_rows:
            mu = dot(beta, design_vector(r["x"]))
            e = r["y"] - mu
            mse += e * e
            pin += pinball(r["y"], mu, 0.5)
        scores[lam] = {"mse": mse / max(1, len(cal_rows)), "pinball50": pin / max(1, len(cal_rows))}
    best = min(lam_grid, key=lambda l: scores[l]["mse"])
    beta = betas[best]
    z = sorted((r["y"] - dot(beta, design_vector(r["x"]))) / r["sigma"] for r in cal_rows if r["sigma"] > 0)
    model = Model(target_id, h, beta, best, FEATURES, z, len(z), sum(grams[d][2] for d in fit_days), fit_days[0],
                  fit_days[-1], cal_days[0], cal_days[-1], {str(l): s for l, s in scores.items()})
    if bootstrap:
        rng = random.Random(seed)
        model.bootstrap_betas = block_bootstrap_betas(grams, fit_days, best, h, bootstrap, rng)
    return model


def block_bootstrap_betas(grams, days, lam, block_len, B, rng) -> list[list[float]]:
    """Stationary block bootstrap over dates (Politis-Romano, mean block length = block_len); each resample refits
    on per-date Gram sums, so B refits cost O(B T k^2)."""
    T = len(days)
    out = []
    p = 1.0 / max(1, block_len)
    for _ in range(B):
        sample = []
        i = rng.randrange(T)
        while len(sample) < T:
            sample.append(days[i])
            i = rng.randrange(T) if rng.random() < p else (i + 1) % T
        out.append(_fit_from_dates(grams, sample, lam)[0])
    return out


def predict(model: Model, x: dict[str, float], sigma: float, *, tau: float = TAU_DEFAULT) -> dict:
    """Forecast fields for one security. ``sigma`` = vol_20 * sqrt(h). ``p_positive`` = P(gross excess return > 0),
    quantity-independent (spec 4.5). The probability that the active return beats the round-trip costs of a
    particular whole-share quantity is computed by the allocator's caller at that quantity, not here."""
    if model.calibration_n < MIN_CALIBRATION:
        return {"abstain": "INSUFFICIENT_CALIBRATION", "calibration_n": model.calibration_n}
    xv = design_vector(x)
    mu = dot(model.beta, xv)
    common = sum(model.beta[j] * xv[j] for j in COMMON_IDX)
    specific = mu - common
    se = se_c = se_s = 0.0
    if len(model.bootstrap_betas) > 1:
        tot, com = [], []
        for b in model.bootstrap_betas:
            tot.append(dot(b, xv))
            com.append(sum(b[j] * xv[j] for j in COMMON_IDX))
        se, se_c, se_s = _sd(tot), _sd(com), _sd([t - c for t, c in zip(tot, com)])
    # Erratum E19: shrink each part by its own uncertainty. The common part is estimated from only as many
    # independent periods as the training window holds (about 15 at 311 dates and h = 20), the stock-specific part
    # from the whole cross-section; shrinking their sum by the total se let the market-timing uncertainty crush the
    # stock-selection signal (5 Nov 2026: se_common 1.30%, se_specific 0.47%, shrink 0.12 instead of 0.53).
    mu_shrunk = shrink(common, se_c, tau) + shrink(specific, se_s, tau) if model.bootstrap_betas else shrink(mu, se, tau)
    z = model.z_sorted
    return {
        "mu_hat": mu, "se": se, "mu_shrunk": mu_shrunk, "sigma_hat": sigma, "tau": tau,
        "mu_common": common, "mu_specific": specific, "se_common": se_c, "se_specific": se_s,
        "q10": mu + sigma * conformal_z(z, 0.1), "q50": mu + sigma * conformal_z(z, 0.5), "q90": mu + sigma * conformal_z(z, 0.9),
        "p_positive": conformal_probability_above(z, (0.0 - mu) / sigma) if sigma > 0 else float("nan"),
        "calibration_n": model.calibration_n, "target_id": model.target_id, "h": model.h, "lam": model.lam,
    }


def pit(model: Model, mu: float, sigma: float, y: float) -> float:
    """Probability integral transform of a realized outcome under the forecast distribution."""
    z = (y - mu) / sigma
    k = sum(1 for v in model.z_sorted if v <= z)
    return (k + 0.5) / (len(model.z_sorted) + 1)
