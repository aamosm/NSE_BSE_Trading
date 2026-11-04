"""Small dense linear algebra and statistics in pure Python (k <= ~30 features)."""
from __future__ import annotations

import math
from typing import Sequence


def zeros(n: int, m: int) -> list[list[float]]:
    return [[0.0] * m for _ in range(n)]


def gram(rows: Sequence[Sequence[float]], y: Sequence[float] | None = None):
    """(X^T X, X^T y) accumulated over rows. Used per date so that date-block bootstraps are O(T k^2)."""
    if not rows:
        return None, None
    k = len(rows[0])
    G = zeros(k, k)
    g = [0.0] * k
    for idx, x in enumerate(rows):
        for i in range(k):
            xi = x[i]
            if xi == 0.0:
                continue
            Gi = G[i]
            for j in range(i, k):
                Gi[j] += xi * x[j]
            if y is not None:
                g[i] += xi * y[idx]
    for i in range(k):
        for j in range(i + 1, k):
            G[j][i] = G[i][j]
    return G, (g if y is not None else None)


def add_gram(A, a, B, b, scale: float = 1.0):
    """A += scale * B (matrices) and a += scale * b (vectors), in place."""
    k = len(B)
    for i in range(k):
        Ai, Bi = A[i], B[i]
        for j in range(k):
            Ai[j] += scale * Bi[j]
        a[i] += scale * b[i]


def cholesky_solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve A x = b for symmetric positive-definite A."""
    n = len(A)
    L = zeros(n, n)
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0.0:
                    raise ValueError("Matrix is not positive definite")
                L[i][i] = math.sqrt(s)
            else:
                L[i][j] = s / L[j][j]
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(L[k][i] * x[k] for k in range(i + 1, n))) / L[i][i]
    return x


def ridge_from_gram(G, g, lam: float, unpenalized: Sequence[int] = ()) -> list[float]:
    """beta = (G + lam*I)^-1 g, leaving the listed coordinates (e.g. the intercept) unpenalized."""
    k = len(G)
    A = [row[:] for row in G]
    skip = set(unpenalized)
    for i in range(k):
        if i not in skip:
            A[i][i] += lam
    return cholesky_solve(A, list(g))


def ridge(X: Sequence[Sequence[float]], y: Sequence[float], lam: float, unpenalized: Sequence[int] = ()) -> list[float]:
    """Worked example (spec section 4.2): X=[[1,0],[0,1],[1,1],[2,1]], y=[1,2,3,5], lam=1 -> (26/19, 28/19)."""
    G, g = gram(X, y)
    return ridge_from_gram(G, g, lam, unpenalized)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def sample_std(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def quantile(sorted_xs: Sequence[float], p: float) -> float:
    """Linear-interpolated quantile of an ascending sequence."""
    n = len(sorted_xs)
    if n == 0:
        raise ValueError("empty")
    pos = (n - 1) * p
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def rank_uniform(values: Sequence[float]) -> list[float]:
    """Cross-sectional rank transform to (-0.5, 0.5]: (rank - 0.5)/n - 0.5, midranks for ties."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2 + 1  # midrank, 1-based
        for t in range(i, j + 1):
            ranks[order[t]] = r
        i = j + 1
    return [(r - 0.5) / n - 0.5 for r in ranks]


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = rank_uniform(a), rank_uniform(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def winsorize(values: Sequence[float], lo_p: float, hi_p: float) -> list[float]:
    s = sorted(values)
    lo, hi = quantile(s, lo_p), quantile(s, hi_p)
    return [min(max(v, lo), hi) for v in values]


def shrunk_correlation(returns: Sequence[Sequence[float]], delta: float = 0.5) -> list[list[float]]:
    """Constant-correlation shrinkage: rho_ij = (1-delta) r_ij + delta * mean off-diagonal r.

    ``returns``: one aligned sequence per asset. Result is positive semidefinite for delta in [0, 1].
    """
    n = len(returns)
    if n == 0:
        return []
    if n == 1:
        return [[1.0]]
    stds = [sample_std(r) for r in returns]
    means = [mean(r) for r in returns]
    R = zeros(n, n)
    for i in range(n):
        R[i][i] = 1.0
        for j in range(i + 1, n):
            if stds[i] == 0 or stds[j] == 0 or math.isnan(stds[i]) or math.isnan(stds[j]):
                c = 0.0
            else:
                m = min(len(returns[i]), len(returns[j]))
                cov = sum((returns[i][t] - means[i]) * (returns[j][t] - means[j]) for t in range(m)) / (m - 1)
                c = max(-1.0, min(1.0, cov / (stds[i] * stds[j])))
            R[i][j] = R[j][i] = c
    off = [R[i][j] for i in range(n) for j in range(i + 1, n)]
    rbar = mean(off) if off else 0.0
    for i in range(n):
        for j in range(n):
            if i != j:
                R[i][j] = (1 - delta) * R[i][j] + delta * rbar
    return R
