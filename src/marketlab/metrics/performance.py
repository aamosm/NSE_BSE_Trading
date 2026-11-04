"""Portfolio return and risk metrics. Definitions and conventions: docs/METRICS.md.

Statistics are floats: they are estimates, not accounting balances. Rupee totals stay Decimal
(see ``trading.py``). Every function raises ``MetricUnavailable`` when its input cannot support the
metric, instead of returning a silent 0, NaN or infinity that could look like a result.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..rules.calendar import MarketCalendar
from ..rules.types import Exchange

Number = float | int | Decimal


class MetricUnavailable(ValueError):
    """The input cannot support this metric (too few observations, zero variance, ...)."""


def _floats(xs: Sequence[Number]) -> list[float]:
    out = [float(x) for x in xs]
    if any(math.isnan(x) or math.isinf(x) for x in out):
        raise MetricUnavailable("NaN or infinite input")
    return out


def _need(xs: Sequence[object], n: int, what: str) -> None:
    if len(xs) < n:
        raise MetricUnavailable(f"{what} needs at least {n} observations, got {len(xs)}")


def _mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs)


def _sample_std(xs: Sequence[float]) -> float:
    _need(xs, 2, "sample standard deviation")
    m = _mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# --------------------------------------------------------------------------- annualisation

def trading_sessions_in_year(calendar: MarketCalendar, exchange: Exchange, year: int) -> int:
    """Regular trading sessions in a loaded calendar year (special sessions excluded).

    Used as periods-per-year for daily series instead of a hard-coded 252. Raises RuleUnknown for
    years whose calendar is not loaded.
    """
    d = date(year, 1, 1)
    n = 0
    while d.year == year:
        if calendar.is_trading_day(exchange, d):
            n += 1
        d += timedelta(days=1)
    return n


# --------------------------------------------------------------------------- returns

def simple_returns(values: Sequence[Number]) -> list[float]:
    """r_t = V_t / V_{t-1} - 1 for a series with no external cash flows."""
    v = _floats(values)
    _need(v, 2, "returns")
    if any(x <= 0 for x in v[:-1]):
        raise MetricUnavailable("non-positive valuation: return undefined")
    return [v[i] / v[i - 1] - 1 for i in range(1, len(v))]


def time_weighted_returns(values: Sequence[Number], flows: Sequence[Number]) -> list[float]:
    """Daily time-weighted returns with external flows at the START of each period.

    ``values[t]`` is the end-of-period net liquidation value; ``flows[t]`` is the net external flow
    (deposit +, withdrawal -) made before trading in period t. ``flows[0]`` must be 0 (the opening
    value already contains it). r_t = V_t / (V_{t-1} + F_t) - 1, so deposits are never returns.
    """
    v, f = _floats(values), _floats(flows)
    if len(v) != len(f):
        raise MetricUnavailable("values and flows must have equal length")
    _need(v, 2, "returns")
    if f[0] != 0:
        raise MetricUnavailable("flows[0] must be 0; include it in the opening value")
    out = []
    for t in range(1, len(v)):
        base = v[t - 1] + f[t]
        if base <= 0:
            raise MetricUnavailable(f"non-positive capital at start of period {t}")
        out.append(v[t] / base - 1)
    return out


def compound_return(returns: Sequence[Number]) -> float:
    r = _floats(returns)
    _need(r, 1, "compound return")
    return math.prod(1 + x for x in r) - 1


def annualized_return(returns: Sequence[Number], periods_per_year: float) -> float:
    """Geometric: (prod(1+r))^(P/n) - 1."""
    r = _floats(returns)
    _need(r, 1, "annualized return")
    growth = math.prod(1 + x for x in r)
    if growth <= 0:
        raise MetricUnavailable("capital wiped out: annualized return undefined")
    return growth ** (periods_per_year / len(r)) - 1


def cagr(start_value: Number, end_value: Number, start: date, end: date) -> float:
    """Calendar CAGR using ACT/365.25 years between the two valuation dates."""
    s, e = float(start_value), float(end_value)
    years = (end - start).days / 365.25
    if years <= 0 or s <= 0 or e <= 0:
        raise MetricUnavailable("CAGR needs positive values and end after start")
    return (e / s) ** (1 / years) - 1


def xirr(cashflows: Sequence[tuple[date, Number]], *, tol: float = 1e-12) -> float:
    """Money-weighted annual return (ACT/365) solving sum CF_i / (1+r)^(d_i/365) = 0.

    Sign convention: money paid into the portfolio is negative, money received (including the final
    valuation) is positive. Solved by bisection on [-0.9999, 100]; raises if there is no sign change.
    """
    _need(cashflows, 2, "XIRR")
    t0 = min(d for d, _ in cashflows)
    cf = [((d - t0).days / 365, float(a)) for d, a in cashflows]
    if not (any(a < 0 for _, a in cf) and any(a > 0 for _, a in cf)):
        raise MetricUnavailable("XIRR needs both negative and positive cash flows")

    def npv(r: float) -> float:
        return math.fsum(a / (1 + r) ** t for t, a in cf)

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        raise MetricUnavailable("XIRR has no root in [-99.99%, 10000%]")
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < tol or hi - lo < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------- dispersion and tails

def volatility(returns: Sequence[Number], periods_per_year: float) -> float:
    """Sample standard deviation (n-1) scaled by sqrt(periods per year)."""
    return _sample_std(_floats(returns)) * math.sqrt(periods_per_year)


def downside_deviation(returns: Sequence[Number], mar_per_period: float, periods_per_year: float) -> float:
    """sqrt(sum(min(0, r - MAR)^2) / n) * sqrt(P), with n = ALL periods (Sortino & Price)."""
    r = _floats(returns)
    _need(r, 1, "downside deviation")
    return math.sqrt(math.fsum(min(0.0, x - mar_per_period) ** 2 for x in r) / len(r)) * math.sqrt(periods_per_year)


def moments(returns: Sequence[Number]) -> tuple[float, float]:
    """(skewness, kurtosis) as population moment ratios m3/m2^1.5 and m4/m2^2; normal kurtosis = 3.

    This is the convention used by the probabilistic/deflated Sharpe ratio formulas.
    """
    r = _floats(returns)
    _need(r, 3, "moments")
    m = _mean(r)
    m2 = math.fsum((x - m) ** 2 for x in r) / len(r)
    if m2 == 0:
        raise MetricUnavailable("zero variance: moments undefined")
    m3 = math.fsum((x - m) ** 3 for x in r) / len(r)
    m4 = math.fsum((x - m) ** 4 for x in r) / len(r)
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def _tail(returns: Sequence[Number], confidence: float) -> list[float]:
    if not 0 < confidence < 1:
        raise MetricUnavailable("confidence must be in (0, 1)")
    r = sorted(_floats(returns))
    _need(r, 1, "tail risk")
    k = math.ceil(len(r) * (1 - confidence) - 1e-12)
    return r[: max(1, k)]


def historical_var(returns: Sequence[Number], confidence: float = 0.95) -> float:
    """Loss (positive number) at the k-th worst return, k = ceil(n * (1 - confidence)), no interpolation."""
    return -_tail(returns, confidence)[-1]


def expected_shortfall(returns: Sequence[Number], confidence: float = 0.95) -> float:
    """Mean loss (positive number) of the k worst returns, k as in ``historical_var``."""
    t = _tail(returns, confidence)
    return -_mean(t)


# --------------------------------------------------------------------------- drawdowns

@dataclass(frozen=True, slots=True)
class Drawdown:
    depth: float  # positive fraction of the running peak, e.g. 0.25 = -25%
    peak_index: int
    trough_index: int
    recovery_index: int | None  # first index back at or above the peak; None = not recovered

    @property
    def decline_periods(self) -> int:
        return self.trough_index - self.peak_index

    @property
    def underwater_periods(self) -> int | None:
        return None if self.recovery_index is None else self.recovery_index - self.peak_index


def drawdown_series(values: Sequence[Number]) -> list[float]:
    """V_t / max(V_0..V_t) - 1 (zero or negative)."""
    v = _floats(values)
    _need(v, 1, "drawdown")
    if any(x <= 0 for x in v):
        raise MetricUnavailable("non-positive valuation in drawdown series")
    peak, out = v[0], []
    for x in v:
        peak = max(peak, x)
        out.append(x / peak - 1)
    return out


def max_drawdown(values: Sequence[Number]) -> Drawdown:
    """Deepest peak-to-trough decline. Ties keep the earliest trough. Zero depth if never below a peak."""
    v = _floats(values)
    dd = drawdown_series(v)
    trough = min(range(len(dd)), key=lambda i: (dd[i], i))
    if dd[trough] == 0:
        return Drawdown(0.0, 0, 0, 0)
    peak_val = max(v[: trough + 1])
    peak = max(i for i in range(trough + 1) if v[i] == peak_val)
    recovery = next((i for i in range(trough + 1, len(v)) if v[i] >= peak_val), None)
    return Drawdown(-dd[trough], peak, trough, recovery)


def ulcer_index(values: Sequence[Number]) -> float:
    """sqrt(mean(drawdown_t^2)) as a fraction (Martin's Ulcer Index without the x100)."""
    dd = drawdown_series(values)
    return math.sqrt(math.fsum(x * x for x in dd) / len(dd))


# --------------------------------------------------------------------------- risk-adjusted ratios

def _excess(returns: Sequence[Number], rf: float | Sequence[float]) -> list[float]:
    r = _floats(returns)
    if isinstance(rf, (int, float)):
        return [x - float(rf) for x in r]
    rf_l = _floats(rf)
    if len(rf_l) != len(r):
        raise MetricUnavailable("risk-free series length differs from returns")
    return [x - y for x, y in zip(r, rf_l)]


def sharpe_ratio(returns: Sequence[Number], *, rf_per_period: float | Sequence[float],
                 periods_per_year: float) -> float:
    """mean(r - rf) / sample_std(r - rf) * sqrt(P). ``rf_per_period`` is required, never defaulted.

    In India the risk-free rate (e.g. 91-day T-bill) is material; passing 0 must be a stated choice.
    """
    ex = _excess(returns, rf_per_period)
    sd = _sample_std(ex)
    if sd == 0:
        raise MetricUnavailable("zero volatility: Sharpe undefined")
    return _mean(ex) / sd * math.sqrt(periods_per_year)


def sortino_ratio(returns: Sequence[Number], *, mar_per_period: float, periods_per_year: float) -> float:
    """mean(r - MAR) * P / downside_deviation (annualized numerator and denominator alike)."""
    r = _floats(returns)
    dd = downside_deviation(r, mar_per_period, periods_per_year)
    if dd == 0:
        raise MetricUnavailable("no returns below MAR: Sortino undefined")
    return _mean([x - mar_per_period for x in r]) * periods_per_year / dd


def calmar_ratio(annual_return: float, max_dd: Drawdown) -> float:
    if max_dd.depth == 0:
        raise MetricUnavailable("no drawdown: Calmar undefined")
    return annual_return / max_dd.depth


def tracking_error(returns: Sequence[Number], benchmark: Sequence[Number], periods_per_year: float) -> float:
    return _sample_std(_excess(returns, _floats(benchmark))) * math.sqrt(periods_per_year)


def information_ratio(returns: Sequence[Number], benchmark: Sequence[Number], periods_per_year: float) -> float:
    active = _excess(returns, _floats(benchmark))
    sd = _sample_std(active)
    if sd == 0:
        raise MetricUnavailable("zero tracking error: information ratio undefined")
    return _mean(active) / sd * math.sqrt(periods_per_year)


def beta(returns: Sequence[Number], benchmark: Sequence[Number]) -> float:
    r, b = _floats(returns), _floats(benchmark)
    if len(r) != len(b):
        raise MetricUnavailable("series lengths differ")
    _need(r, 2, "beta")
    mr, mb = _mean(r), _mean(b)
    var_b = math.fsum((y - mb) ** 2 for y in b)
    if var_b == 0:
        raise MetricUnavailable("benchmark has zero variance")
    return math.fsum((x - mr) * (y - mb) for x, y in zip(r, b)) / var_b


def per_period_rate(annual_rate: float, periods_per_year: float) -> float:
    """Geometric de-annualisation: (1 + R)^(1/P) - 1."""
    return (1 + annual_rate) ** (1 / periods_per_year) - 1
