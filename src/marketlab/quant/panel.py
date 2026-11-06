"""Daily price panel built from stored official bhavcopies (actual traded prices) and index files.

Tables (SQLite, ``market/panel.sqlite3``, rebuildable from the raw files):
  bars(isin, day, symbol, series, name, open, high, low, close, prev_close, volume, value, trades)
  sessions(day)                      sessions present in the panel (one bhavcopy each)
  index_levels(name, day, open, high, low, close, pe, pb, dy)
  implied_factors(isin, day, factor) exchange-implied corporate-action factors (spec section 2.4)
  factor_coverage(day, status)       CHECKED when the calendar's previous session is stored, else UNCHECKED
  discontinuities(isin, day, kind, ratio, other_isin)
      PRICE_DISCONTINUITY  close / exchange base price outside [0.8, 1.25]: in the 2025 UDiFF files the base price
                           (PrvsClsgPric) is NOT adjusted on split or bonus ex-dates (pilot, 5 Nov 2026), so an action
                           shows up as a price jump that no band permits, not as an implied factor
      IDENTITY_END / IDENTITY_START  the same NSE symbol moves to a new ISIN between consecutive sessions (splits
                           usually issue a new ISIN); the old ISIN stops trading, the new one starts without history

``Panel.view(end)`` gives a read-only view whose every query stops at ``end``: the development evaluation reads the
panel only through a view ending before the frozen holdout, so later prices cannot reach it, and
``content_hash`` fingerprints exactly what a view can see.

``prev_close`` is the exchange's base price for the day: on an ex-date it is already adjusted, so the daily log
return ln(close / prev_close) needs no separate adjustment, and the factor prev_close / prior_close records the
action. ETFs are flagged by name so that the universe can exclude them.
"""
from __future__ import annotations

import copy
import hashlib
import math
import sqlite3
from array import array
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import sources
from ..master import parse_bhavcopy, parse_legacy_bhavcopy

EQUITY_SERIES = ("EQ", "BE", "BZ", "SM", "ST", "SZ")
FACTOR_TOLERANCE = 0.0005  # |prev_close/prior_close - 1| above this is an adjustment (or a data problem)
# One-session close/base-price ratio outside this is an unexplained jump. Just beyond the widest static band (20%), so
# a close pinned at a 20% circuit (ratio 0.80 / 1.20) is real trading, not an action. Unbanded (F&O) stocks can move
# further on news; without an action history such moves are excluded too and counted (a known bias risk).
DISCONTINUITY_LOW, DISCONTINUITY_HIGH = 0.795, 1.255
ETF_MARKERS = ("ETF", "BEES", "EXCHANGE TRADED")  # spec 3.1: names containing ETF, plus INF-prefixed ISINs


@dataclass(frozen=True, slots=True)
class Bar:
    day: date
    symbol: str
    series: str
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    volume: float
    value: float
    trades: int


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


class Panel:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=30)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS bars (isin TEXT NOT NULL, day TEXT NOT NULL, symbol TEXT, series TEXT, name TEXT,
                open REAL, high REAL, low REAL, close REAL, prev_close REAL, volume REAL, value REAL, trades INTEGER,
                PRIMARY KEY (isin, day));
            CREATE INDEX IF NOT EXISTS bars_day ON bars(day);
            CREATE TABLE IF NOT EXISTS sessions (day TEXT PRIMARY KEY, source_sha256 TEXT);
            CREATE TABLE IF NOT EXISTS index_levels (name TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL,
                close REAL, pe REAL, pb REAL, dy REAL, PRIMARY KEY (name, day));
            CREATE TABLE IF NOT EXISTS implied_factors (isin TEXT NOT NULL, day TEXT NOT NULL, factor REAL NOT NULL,
                prior_close REAL, prev_close REAL, PRIMARY KEY (isin, day));
            CREATE TABLE IF NOT EXISTS factor_coverage (day TEXT PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS discontinuities (isin TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
                ratio REAL, other_isin TEXT, PRIMARY KEY (isin, day, kind));
        """)
        self.end_limit: date | None = None

    def view(self, end: date | None) -> "Panel":
        """A view sharing this connection whose queries never return anything after ``end`` (None: no limit)."""
        v = copy.copy(self)
        v.end_limit = end if self.end_limit is None or end is None else min(end, self.end_limit)
        if end is None:
            v.end_limit = self.end_limit
        return v

    def _end(self, end: date | None) -> date | None:
        if self.end_limit is None:
            return end
        return self.end_limit if end is None else min(end, self.end_limit)

    # ---- building ------------------------------------------------------------------------------

    def add_session(self, day: date, rows, sha256: str = "") -> int:
        """Insert one session's equity rows (parsed UDiFF dicts). Idempotent per (isin, day)."""
        out = []
        for r in rows:
            if r.get("SctySrs") not in EQUITY_SERIES or not r.get("ISIN"):
                continue
            out.append((r["ISIN"], day.isoformat(), r.get("TckrSymb"), r["SctySrs"], r.get("FinInstrmNm", ""),
                        _f(r.get("OpnPric")), _f(r.get("HghPric")), _f(r.get("LwPric")), _f(r.get("ClsPric")),
                        _f(r.get("PrvsClsgPric")), _f(r.get("TtlTradgVol")), _f(r.get("TtlTrfVal")),
                        int(_f(r.get("TtlNbOfTxsExctd")) or 0)))
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (day.isoformat(), sha256))
        return len(out)

    def add_index_file(self, day: date, raw: bytes) -> int:
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        out = []
        for r in rows:
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            name = r.get("Index Name")
            if not name:
                continue
            out.append((name, day.isoformat(), _f(r.get("Open Index Value")), _f(r.get("High Index Value")),
                        _f(r.get("Low Index Value")), _f(r.get("Closing Index Value")), _f(r.get("P/E")),
                        _f(r.get("P/B")), _f(r.get("Div Yield"))))
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO index_levels VALUES (?,?,?,?,?,?,?,?,?)", out)
        return len(out)

    def compute_implied_factors(self, calendar=None) -> dict:
        """prev_close / prior-session close where they differ by more than the tolerance (spec section 2.4).

        Only computed for a day whose exchange-calendar previous trading day is itself in the panel; a day whose
        prior session is missing cannot be checked and is listed under ``unchecked``. Recomputed from scratch.
        """
        from ..rules.calendar import MarketCalendar
        from ..rules.types import Exchange, RuleUnknown
        cal = calendar or MarketCalendar()
        days = self.sessions()
        have = set(days)
        n, unchecked = 0, []
        with self.db:
            self.db.execute("DELETE FROM implied_factors")
            self.db.execute("DELETE FROM factor_coverage")
            prior_day = None
            for d in days:
                try:
                    prev_day = cal.previous_trading_day(Exchange.NSE, d)
                except RuleUnknown:
                    unchecked.append(d.isoformat())
                    self.db.execute("INSERT INTO factor_coverage VALUES (?, 'UNCHECKED')", (d.isoformat(),))
                    continue
                if prev_day not in have:
                    unchecked.append(d.isoformat())
                    self.db.execute("INSERT INTO factor_coverage VALUES (?, 'UNCHECKED')", (d.isoformat(),))
                    continue
                self.db.execute("INSERT INTO factor_coverage VALUES (?, 'CHECKED')", (d.isoformat(),))
                if prior_day != prev_day:
                    prior = {r[0]: r[1] for r in self.db.execute("SELECT isin, close FROM bars WHERE day=?", (prev_day.isoformat(),))}
                    prior_day = prev_day
                rows = self.db.execute("SELECT isin, close, prev_close FROM bars WHERE day=?", (d.isoformat(),)).fetchall()
                for isin, close, prev in rows:
                    pc = prior.get(isin)
                    if pc and prev and pc > 0 and abs(prev / pc - 1) > FACTOR_TOLERANCE:
                        self.db.execute("INSERT OR REPLACE INTO implied_factors VALUES (?,?,?,?,?)",
                                        (isin, d.isoformat(), prev / pc, pc, prev))
                        n += 1
                prior = {isin: close for isin, close, _ in rows}  # next day's prior, if consecutive
                prior_day = d
        return {"factors": n, "unchecked_days": unchecked}

    # ---- queries -------------------------------------------------------------------------------

    def sessions(self, start: date | None = None, end: date | None = None) -> list[date]:
        end = self._end(end)
        q, args = "SELECT day FROM sessions", []
        conds = []
        if start:
            conds.append("day >= ?"); args.append(start.isoformat())
        if end:
            conds.append("day <= ?"); args.append(end.isoformat())
        if conds:
            q += " WHERE " + " AND ".join(conds)
        return [date.fromisoformat(r[0]) for r in self.db.execute(q + " ORDER BY day", args)]

    def bars(self, isin: str, start: date | None = None, end: date | None = None) -> list[Bar]:
        end = self._end(end)
        q, args = "SELECT day, symbol, series, open, high, low, close, prev_close, volume, value, trades FROM bars WHERE isin=?", [isin]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return [Bar(date.fromisoformat(r[0]), *r[1:]) for r in self.db.execute(q + " ORDER BY day", args)]

    def cross_section(self, day: date) -> list[tuple[str, Bar]]:
        if self.end_limit is not None and day > self.end_limit:
            return []
        rows = self.db.execute("SELECT isin, day, symbol, series, open, high, low, close, prev_close, volume, value, trades "
                               "FROM bars WHERE day=?", (day.isoformat(),)).fetchall()
        return [(r[0], Bar(date.fromisoformat(r[1]), *r[2:])) for r in rows]

    def names_on(self, day: date) -> dict[str, str]:
        """Security names as printed in that session's bhavcopy (dated classification)."""
        if self.end_limit is not None and day > self.end_limit:
            return {}
        return {r[0]: r[1] or "" for r in self.db.execute("SELECT isin, name FROM bars WHERE day=?", (day.isoformat(),))}

    def is_etf(self, isin: str, day: date | None = None, name: str | None = None) -> bool:
        """ETF by the name in force on ``day`` (the latest bar at or before it), never a later name."""
        if name is None:
            end = self._end(day)
            q, args = "SELECT name FROM bars WHERE isin=?", [isin]
            if end:
                q += " AND day <= ?"
                args.append(end.isoformat())
            row = self.db.execute(q + " ORDER BY day DESC LIMIT 1", args).fetchone()
            name = row[0] if row else ""
        return is_etf_name(isin, name)

    def isins(self) -> list[str]:
        if self.end_limit is not None:
            return [r[0] for r in self.db.execute("SELECT DISTINCT isin FROM bars WHERE day <= ? ORDER BY isin",
                                                  (self.end_limit.isoformat(),))]
        return [r[0] for r in self.db.execute("SELECT DISTINCT isin FROM bars ORDER BY isin")]

    def compute_discontinuities(self, calendar=None) -> dict:
        """Price discontinuities and ISIN successions (see the module docstring). Recomputed from scratch."""
        from ..rules.calendar import MarketCalendar
        from ..rules.types import Exchange, RuleUnknown
        cal = calendar or MarketCalendar()
        days = self.sessions()
        have = set(days)
        n_price = n_id = 0
        with self.db:
            self.db.execute("DELETE FROM discontinuities")
            for isin, day, c, pc in self.db.execute(
                    "SELECT isin, day, close, prev_close FROM bars WHERE prev_close > 0 AND close > 0 "
                    "AND (close / prev_close < ? OR close / prev_close > ?)", (DISCONTINUITY_LOW, DISCONTINUITY_HIGH)).fetchall():
                self.db.execute("INSERT OR REPLACE INTO discontinuities VALUES (?,?,?,?,NULL)", (isin, day, "PRICE_DISCONTINUITY", c / pc))
                n_price += 1
            first = {}
            last = {}
            for isin, symbol, series, lo, hi in self.db.execute(
                    "SELECT isin, symbol, series, min(day), max(day) FROM bars GROUP BY isin, symbol, series").fetchall():
                first.setdefault((symbol, series), []).append((lo, hi, isin))
            for (symbol, series), spans in first.items():
                spans.sort()
                for (lo1, hi1, old), (lo2, hi2, new) in zip(spans, spans[1:]):
                    d2 = date.fromisoformat(lo2)
                    try:
                        prev = cal.previous_trading_day(Exchange.NSE, d2)
                    except RuleUnknown:
                        continue
                    if old != new and date.fromisoformat(hi1) == prev and prev in have:
                        self.db.execute("INSERT OR REPLACE INTO discontinuities VALUES (?,?,?,NULL,?)", (old, lo2, "IDENTITY_END", new))
                        self.db.execute("INSERT OR REPLACE INTO discontinuities VALUES (?,?,?,NULL,?)", (new, lo2, "IDENTITY_START", old))
                        n_id += 1
        return {"price_discontinuities": n_price, "identity_changes": n_id}

    def discontinuities(self, isin: str | None = None, start: date | None = None, end: date | None = None) -> dict:
        """{isin: {day: (kind, ratio, other_isin)}} (one security when ``isin`` is given: {day: ...})."""
        end = self._end(end)
        q, args = "SELECT isin, day, kind, ratio, other_isin FROM discontinuities WHERE 1=1", []
        if isin:
            q += " AND isin = ?"; args.append(isin)
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        out: dict = {}
        for i, d, kind, ratio, other in self.db.execute(q, args):
            out.setdefault(i, {}).setdefault(date.fromisoformat(d), []).append((kind, ratio, other))
        return out.get(isin, {}) if isin else out

    def unchecked_days(self, start: date | None = None, end: date | None = None) -> set[date]:
        """Days whose corporate-action factor could not be computed (previous session missing or calendar unknown)."""
        end = self._end(end)
        q, args = "SELECT day FROM factor_coverage WHERE status='UNCHECKED'", []
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return {date.fromisoformat(r[0]) for r in self.db.execute(q, args)}

    def content_hash(self) -> str:
        """SHA-256 over every row this panel (or view) can see: sessions with their source hashes, bars, index
        levels, implied factors and factor coverage. Appending or changing rows after a view's end leaves the
        view's hash unchanged."""
        h = hashlib.sha256()
        end = self.end_limit.isoformat() if self.end_limit else "9999-12-31"
        for table, cols in (("sessions", "day, source_sha256"),
                            ("bars", "isin, day, symbol, series, name, open, high, low, close, prev_close, volume, value, trades"),
                            ("index_levels", "name, day, open, high, low, close, pe, pb, dy"),
                            ("implied_factors", "isin, day, factor"), ("factor_coverage", "day, status")):
            h.update(table.encode())
            order = "day" if table in ("sessions", "factor_coverage") else ("name, day" if table == "index_levels" else "isin, day")
            for row in self.db.execute(f"SELECT {cols} FROM {table} WHERE day <= ? ORDER BY {order}", (end,)):
                h.update(repr(row).encode())
        return h.hexdigest()

    def index_levels(self, name: str, start: date | None = None, end: date | None = None) -> dict[date, tuple[float, float]]:
        end = self._end(end)
        q, args = "SELECT day, open, close FROM index_levels WHERE name=?", [name]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return {date.fromisoformat(r[0]): (r[1], r[2]) for r in self.db.execute(q + " ORDER BY day", args)}

    def implied_factors(self, isin: str, start: date | None = None, end: date | None = None) -> dict[date, float]:
        end = self._end(end)
        q, args = "SELECT day, factor FROM implied_factors WHERE isin=?", [isin]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return {date.fromisoformat(r[0]): r[1] for r in self.db.execute(q, args)}

    def series_arrays(self, isin: str, end: date | None = None) -> dict:
        """Compact columns for rolling computations: day list plus array('d') columns (bars up to ``end``)."""
        bars = self.bars(isin, None, end)
        cols = {k: array("d") for k in ("open", "high", "low", "close", "prev_close", "volume", "value")}
        days = []
        for b in bars:
            days.append(b.day)
            for k in cols:
                cols[k].append(getattr(b, k))
        return {"days": days, **cols}

    def close(self):
        self.db.close()


def build(market: Path, path: Path | None = None, after: date | None = None, calendar=None) -> dict:
    """Load every stored NSE bhavcopy and index file into the panel (idempotent), then compute implied factors."""
    panel = Panel(path or market / "panel.sqlite3")
    if calendar is None:
        calendar = sources.load_calendar_for(market)[0]
    db = sources.catalog(market)
    loaded, indices, legacy = 0, 0, 0
    try:
        rows = db.db.execute("SELECT subject, payload FROM observations WHERE kind='source_file'").fetchall()
        import json
        files = []
        for subj, payload in rows:
            p = json.loads(payload)
            if p.get("result") != "STORED":
                continue
            path_ = p.get("path", "")
            if path_.startswith(("raw/nse_bhavcopy/", "raw/nse_bhavcopy_legacy/", "raw/nse_indices_close/")):
                files.append((subj, path_, p.get("sha256", "")))
        have = {d.isoformat() for d in panel.sessions()}
        udiff_days = {s for s, p_, _ in files if p_.startswith("raw/nse_bhavcopy/")}
        for subj, path_, sha in sorted(files):
            d = date.fromisoformat(subj)
            if after and d < after:
                continue
            if path_.startswith("raw/nse_bhavcopy/"):
                if subj in have:
                    continue
                raw = sources.read_raw(market, "nse_bhavcopy", d)
                if raw:
                    panel.add_session(d, parse_bhavcopy(raw, zipped=True), sha)
                    loaded += 1
            elif path_.startswith("raw/nse_bhavcopy_legacy/"):
                if subj in have or subj in udiff_days:  # the UDiFF file is preferred where both exist
                    continue
                raw = sources.read_raw(market, "nse_bhavcopy_legacy", d)
                if raw:
                    panel.add_session(d, parse_legacy_bhavcopy(raw), sha)
                    loaded += 1
                    legacy += 1
            else:
                raw = sources.read_raw(market, "nse_indices_close", d)
                if raw:
                    indices += panel.add_index_file(d, raw)
        factors = panel.compute_implied_factors(calendar)
        factors |= panel.compute_discontinuities(calendar)
    finally:
        db.close()
    out = {"sessions_loaded": loaded, "legacy_sessions_loaded": legacy, "sessions_total": len(panel.sessions()), "index_rows": indices,
           "implied_factors": factors["factors"], "factor_unchecked_days": len(factors["unchecked_days"]),
           "price_discontinuities": factors["price_discontinuities"], "identity_changes": factors["identity_changes"],
           "isins": len(panel.isins()), "path": str(panel.path)}
    panel.close()
    return out


def is_etf_name(isin: str, name: str | None) -> bool:
    n = (name or "").upper()
    return isin.startswith("INF") or any(m in n for m in ETF_MARKERS)  # INF = mutual fund / ETF ISIN prefix


def log_return(close: float, prev_close: float) -> float:
    if not (close > 0 and prev_close > 0):
        return float("nan")
    return math.log(close / prev_close)
