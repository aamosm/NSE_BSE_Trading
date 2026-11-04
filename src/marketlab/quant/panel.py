"""Daily price panel built from stored official bhavcopies (actual traded prices) and index files.

Tables (SQLite, ``market/panel.sqlite3``, rebuildable from the raw files):
  bars(isin, day, symbol, series, name, open, high, low, close, prev_close, volume, value, trades)
  sessions(day)                      sessions present in the panel (one bhavcopy each)
  index_levels(name, day, open, high, low, close, pe, pb, dy)
  implied_factors(isin, day, factor) exchange-implied corporate-action factors (spec section 2.4)

``prev_close`` is the exchange's base price for the day: on an ex-date it is already adjusted, so the daily log
return ln(close / prev_close) needs no separate adjustment, and the factor prev_close / prior_close records the
action. ETFs are flagged by name so that the universe can exclude them.
"""
from __future__ import annotations

import math
import sqlite3
from array import array
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import sources
from ..master import parse_bhavcopy

EQUITY_SERIES = ("EQ", "BE", "BZ", "SM", "ST", "SZ")
FACTOR_TOLERANCE = 0.0005  # |prev_close/prior_close - 1| above this is an adjustment (or a data problem)
ETF_MARKERS = ("ETF", "BEES", "EXCHANGE TRADED", "GOLD", "SILVER", "LIQUID")


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
        """)

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
            prior_day = None
            for d in days:
                try:
                    prev_day = cal.previous_trading_day(Exchange.NSE, d)
                except RuleUnknown:
                    unchecked.append(d.isoformat())
                    continue
                if prev_day not in have:
                    unchecked.append(d.isoformat())
                    continue
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
        q, args = "SELECT day, symbol, series, open, high, low, close, prev_close, volume, value, trades FROM bars WHERE isin=?", [isin]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return [Bar(date.fromisoformat(r[0]), *r[1:]) for r in self.db.execute(q + " ORDER BY day", args)]

    def cross_section(self, day: date) -> list[tuple[str, Bar]]:
        rows = self.db.execute("SELECT isin, day, symbol, series, open, high, low, close, prev_close, volume, value, trades "
                               "FROM bars WHERE day=?", (day.isoformat(),)).fetchall()
        return [(r[0], Bar(date.fromisoformat(r[1]), *r[2:])) for r in rows]

    def is_etf(self, isin: str) -> bool:
        row = self.db.execute("SELECT name FROM bars WHERE isin=? ORDER BY day DESC LIMIT 1", (isin,)).fetchone()
        name = (row[0] or "").upper() if row else ""
        return any(m in name for m in ETF_MARKERS) or isin.startswith("INF")  # INF = mutual fund / ETF ISIN prefix

    def isins(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT isin FROM bars ORDER BY isin")]

    def index_levels(self, name: str, start: date | None = None, end: date | None = None) -> dict[date, tuple[float, float]]:
        q, args = "SELECT day, open, close FROM index_levels WHERE name=?", [name]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return {date.fromisoformat(r[0]): (r[1], r[2]) for r in self.db.execute(q + " ORDER BY day", args)}

    def implied_factors(self, isin: str, start: date | None = None, end: date | None = None) -> dict[date, float]:
        q, args = "SELECT day, factor FROM implied_factors WHERE isin=?", [isin]
        if start:
            q += " AND day >= ?"; args.append(start.isoformat())
        if end:
            q += " AND day <= ?"; args.append(end.isoformat())
        return {date.fromisoformat(r[0]): r[1] for r in self.db.execute(q, args)}

    def series_arrays(self, isin: str) -> dict:
        """Compact columns for rolling computations: day list plus array('d') columns."""
        bars = self.bars(isin)
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
        calendar = sources.load_calendar(market)[0]
    db = sources.catalog(market)
    loaded, indices = 0, 0
    try:
        rows = db.db.execute("SELECT subject, payload FROM observations WHERE kind='source_file'").fetchall()
        import json
        files = []
        for subj, payload in rows:
            p = json.loads(payload)
            if p.get("result") != "STORED":
                continue
            path_ = p.get("path", "")
            if path_.startswith("raw/nse_bhavcopy/") or path_.startswith("raw/nse_indices_close/"):
                files.append((subj, path_, p.get("sha256", "")))
        have = {d.isoformat() for d in panel.sessions()}
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
            else:
                raw = sources.read_raw(market, "nse_indices_close", d)
                if raw:
                    indices += panel.add_index_file(d, raw)
        factors = panel.compute_implied_factors(calendar)
    finally:
        db.close()
    out = {"sessions_loaded": loaded, "sessions_total": len(panel.sessions()), "index_rows": indices,
           "implied_factors": factors["factors"], "factor_unchecked_days": len(factors["unchecked_days"]),
           "isins": len(panel.isins()), "path": str(panel.path)}
    panel.close()
    return out


def log_return(close: float, prev_close: float) -> float:
    if not (close > 0 and prev_close > 0):
        return float("nan")
    return math.log(close / prev_close)
