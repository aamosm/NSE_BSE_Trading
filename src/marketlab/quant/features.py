"""Feature set A (spec section 3.3), computed per security in one pass over its history (O(n)).

The replay dataset and the live decision use the same rows: ``evaluate.build_dataset`` computes them for every
decision session and ``decide`` takes the latest session's rows from that same dataset. Every value at session D
depends only on bars and index levels at or before D. A missing or non-finite value stays missing (NaN) through
standardization, so the decision abstains with FEATURE_COVERAGE instead of seeing a clipped number.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import date

from .linalg import rank_uniform, winsorize
from .panel import Panel, log_return

STOCK_FEATURES = ("mom_12_1", "rev_5", "ret_20", "vol_20", "park_20", "amihud_20", "lvalue_20", "range_250", "gap_1")
MARKET_FEATURES = ("mkt_20", "mkt_60", "mkt_vol_20", "breadth_50")
FEATURES = STOCK_FEATURES + MARKET_FEATURES
MIN_HISTORY = 251  # sessions of history before the first complete row


def _prefix(xs):
    out = [0.0]
    s = 0.0
    for x in xs:
        s += x
        out.append(s)
    return out


class _RollingMedian:
    """Median of the last w values; O(w) per step, fine for w = 20."""

    def __init__(self, w):
        self.w, self.buf = w, deque()

    def push(self, x):
        self.buf.append(x)
        if len(self.buf) > self.w:
            self.buf.popleft()
        s = sorted(self.buf)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def stock_feature_rows(series: dict, bad_days: set[date] | None = None) -> dict[date, dict[str, float]]:
    """``series`` from Panel.series_arrays. Returns {day: features} for days with full history. A day in
    ``bad_days`` (an unexplained price discontinuity) makes every window containing it incomplete."""
    days, o, h, l, c, pc, val = (series[k] for k in ("days", "open", "high", "low", "close", "prev_close", "value"))
    n = len(days)
    bad_days = bad_days or set()
    r = [float("nan") if days[i] in bad_days else log_return(c[i], pc[i]) for i in range(n)]
    hl2 = [(math.log(h[i] / l[i]) ** 2) if h[i] > 0 and l[i] > 0 else float("nan") for i in range(n)]
    ami = [abs(r[i]) / (val[i] / 1e7) if val[i] > 0 and not math.isnan(r[i]) else float("nan") for i in range(n)]
    ok = [not (math.isnan(r[i]) or math.isnan(hl2[i]) or math.isnan(ami[i])) for i in range(n)]
    # prefix sums over clean values; a window containing a bad value is skipped via a bad-count prefix
    P_r, P_r2 = _prefix([x if ok[i] else 0.0 for i, x in enumerate(r)]), _prefix([x * x if ok[i] else 0.0 for i, x in enumerate(r)])
    P_hl, P_ami = _prefix([hl2[i] if ok[i] else 0.0 for i in range(n)]), _prefix([ami[i] if ok[i] else 0.0 for i in range(n)])
    P_bad = _prefix([0.0 if ok[i] else 1.0 for i in range(n)])
    med = _RollingMedian(20)
    lo_q, hi_q = deque(), deque()  # monotonic deques for rolling min low / max high over 250
    out = {}
    for i in range(n):
        mv = med.push(val[i])
        while lo_q and l[lo_q[-1]] >= l[i]:
            lo_q.pop()
        lo_q.append(i)
        while hi_q and h[hi_q[-1]] <= h[i]:
            hi_q.pop()
        hi_q.append(i)
        while lo_q[0] <= i - 250:
            lo_q.popleft()
        while hi_q[0] <= i - 250:
            hi_q.popleft()
        if i < MIN_HISTORY - 1 or P_bad[i + 1] - P_bad[i + 1 - 251] > 0 or mv <= 0:
            continue

        def wsum(P, w):
            return P[i + 1] - P[i + 1 - w]
        v20 = (wsum(P_r2, 20) - wsum(P_r, 20) ** 2 / 20) / 19
        out[days[i]] = {
            "mom_12_1": wsum(P_r, 251) - wsum(P_r, 21),  # sessions i-250..i-21 (i-20..i excluded)
            "rev_5": wsum(P_r, 5),
            "ret_20": wsum(P_r, 20),
            "vol_20": math.sqrt(max(v20, 0.0)),
            "park_20": math.sqrt(wsum(P_hl, 20) / 20 / (4 * math.log(2))),
            "amihud_20": wsum(P_ami, 20) / 20,
            "lvalue_20": math.log(mv),
            "range_250": (c[i] - l[lo_q[0]]) / (h[hi_q[0]] - l[lo_q[0]]) if h[hi_q[0]] > l[lo_q[0]] else 0.5,
            "gap_1": math.log(o[i] / pc[i]) if o[i] > 0 and pc[i] > 0 else 0.0,
        }
    return out


def market_feature_rows(index_levels: dict[date, tuple[float, float]], breadth: dict[date, float]) -> dict[date, dict[str, float]]:
    days = sorted(index_levels)
    closes = [index_levels[d][1] for d in days]
    r = [math.log(closes[i] / closes[i - 1]) if i > 0 and closes[i - 1] > 0 else 0.0 for i in range(len(days))]
    P, P2 = _prefix(r), _prefix([x * x for x in r])
    out = {}
    for i, d in enumerate(days):
        if i < 60:
            continue
        v = (P2[i + 1] - P2[i + 1 - 20] - (P[i + 1] - P[i + 1 - 20]) ** 2 / 20) / 19
        out[d] = {"mkt_20": P[i + 1] - P[i + 1 - 20], "mkt_60": P[i + 1] - P[i + 1 - 60],
                  "mkt_vol_20": math.sqrt(max(v, 0.0)), "breadth_50": breadth.get(d, float("nan"))}
    return out


def breadth_50(universe_by_day: dict[date, list[str]], closes: dict[str, dict[date, float]],
               sessions: list[date]) -> dict[date, float]:
    """Fraction of the day's universe whose close is above its 50-session average close. ``sessions`` are exchange
    sessions: a security (or a day) missing any of the 50 does not count, and with none counted breadth is missing."""
    out = {}
    idx = {d: i for i, d in enumerate(sessions)}
    for d, isins in universe_by_day.items():
        i = idx.get(d)
        if i is None or i < 49 or not isins:
            continue
        window = sessions[i - 49:i + 1]
        above = total = 0
        for isin in isins:
            cs = closes.get(isin, {})
            vals = [cs[w] for w in window if w in cs]
            if len(vals) == 50:
                total += 1
                above += 1 if cs[d] > sum(vals) / 50 else 0
        if total:
            out[d] = above / total
    return out


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def rank_stock_features(rows: list[dict]) -> list[dict]:
    """Stock features -> cross-sectional rank uniform on (-0.5, 0.5] per date, over the rows given (the whole
    decision-time cross-section, not only rows whose outcome later resolved). Non-finite values stay NaN."""
    by_day: dict[date, list[int]] = {}
    for i, r in enumerate(rows):
        by_day.setdefault(r["day"], []).append(i)
    out = [dict(r, x=dict(r.get("x") or {})) for r in rows]
    for d, idxs in by_day.items():
        for f in STOCK_FEATURES:
            ok = [i for i in idxs if _finite(rows[i]["features"].get(f))]
            vals = [rows[i]["features"][f] for i in ok]
            ranks = rank_uniform(vals) if len(vals) > 1 else [0.0] * len(vals)
            for i in idxs:
                out[i]["x"][f] = float("nan")
            for i, v in zip(ok, ranks):
                out[i]["x"][f] = v
    return out


def scale_market_features(rows: list[dict], market_stats: dict | None) -> list[dict]:
    """Market features -> z-score with (mean, std) fitted on training dates, winsorized at +-3 AFTER checking the
    value is finite (a NaN must not become +3). Without usable stats a feature is missing."""
    for r in rows:
        x = r.setdefault("x", {})
        for f in MARKET_FEATURES:
            v = r["features"].get(f, float("nan"))
            st = (market_stats or {}).get(f)
            if not _finite(v) or not st or not (st[1] > 0):
                x[f] = float("nan")
                continue
            z = (v - st[0]) / st[1]
            x[f] = max(-3.0, min(3.0, z))
    return rows


def standardize_by_date(rows: list[dict], market_stats: dict | None = None) -> list[dict]:
    """Both steps (stock ranks per date, market z-scores with training stats). Rows need day, isin, features."""
    return scale_market_features(rank_stock_features(rows), market_stats)


def missing_features(x: dict) -> list[str]:
    return [f for f in FEATURES if not _finite(x.get(f))]


def market_stats(rows: list[dict]) -> dict:
    """Per-feature (mean, std) of market features over distinct training dates (one value per date)."""
    seen, vals = set(), {f: [] for f in MARKET_FEATURES}
    for r in rows:
        if r["day"] in seen:
            continue
        seen.add(r["day"])
        for f in MARKET_FEATURES:
            v = r["features"].get(f, float("nan"))
            if not math.isnan(v):
                vals[f].append(v)
    out = {}
    for f, xs in vals.items():
        if len(xs) >= 2:
            m = sum(xs) / len(xs)
            s = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            out[f] = (m, s)
    return out


def design_vector(x: dict[str, float]) -> list[float]:
    return [1.0] + [x[f] for f in FEATURES]


def winsorize_targets(ys: list[float], lo=0.025, hi=0.975) -> list[float]:
    return winsorize(ys, lo, hi) if len(ys) >= 40 else list(ys)
