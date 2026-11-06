"""Bulk download of Kite daily candles for every NSE equity instrument and the main indices (read-only).

Why it exists: the research panel holds ~580 sessions; the evaluation and the forecast's uncertainty both need
years more. Kite's historical endpoint is the fastest lawful source while the owner's daily session is valid.

How it works:
  1. one request for the NSE instrument dump (stored raw, hashed);
  2. for each instrument, daily candles in chunks of at most 2,000 calendar days, NEWEST first, stopping at the
     first empty chunk (the listing date has been passed), so a young stock costs one request and an old one
     about five;
  3. every response is written once under ``<out>/day/<token>/<from>_<to>.json`` with its SHA-256 appended to
     ``<out>/manifest.jsonl``; a re-run skips every chunk already in the manifest (resume after a crash or an
     expired session).

What it is NOT:
  - the historical universe: the dump lists instruments alive TODAY, so delisted stocks are absent. Using these
    candles as the universe is survivorship bias; the exchange bhavcopies define who existed on each date and
    these candles only fill prices for instruments the bhavcopies confirm (see kite_backfill.py).
  - actual traded prices: Kite adjusts candles for splits, bonuses, rights and extraordinary dividends as of
    the retrieval date (``adjustment_basis: PROVIDER_AS_OF_RETRIEVAL``). Never apply the same corporate
    actions again; never treat them as fills.

Rate: the read-only client spaces calls at least 1.05 s apart, below Kite's published historical limit. An HTTP
429 backs off 30 s and retries at most three times. An expired or invalidated session stops the run cleanly and
the manifest keeps everything done so far.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .common import IST, atomic_json, now
from .kite import AuthenticationRequired, KiteError

CHUNK_DAYS = 2000  # Kite's documented maximum span for one 'day' interval request
EARLIEST = date(2000, 1, 1)
INDEX_NAMES = ("NIFTY 50", "NIFTY 500", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY MIDCAP 100",
               "NIFTY SMALLCAP 100", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY MICROCAP 250", "INDIA VIX",
               "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY AUTO", "NIFTY METAL", "NIFTY ENERGY",
               "NIFTY REALTY", "NIFTY FIN SERVICE", "NIFTY PSU BANK", "NIFTY MEDIA", "NIFTY INFRA")
METADATA = {"series_kind": "PROVIDER_ORIGINAL", "adjustment_basis": "PROVIDER_AS_OF_RETRIEVAL",
            "provider": "kite", "interval": "day",
            "warning": "adjusted by the provider as of retrieval; not traded prices; not a historical universe"}


@dataclass(frozen=True, slots=True)
class Instrument:
    token: int
    symbol: str
    name: str
    segment: str
    kind: str  # instrument_type
    lot_size: int
    tick_size: float

    def to_json(self) -> dict:
        return {"token": self.token, "symbol": self.symbol, "name": self.name, "segment": self.segment,
                "instrument_type": self.kind, "lot_size": self.lot_size, "tick_size": self.tick_size}


def parse_instruments(text: str) -> list[Instrument]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(Instrument(int(row["instrument_token"]), row["tradingsymbol"].strip(), (row.get("name") or "").strip(),
                                  (row.get("segment") or "").strip(), (row.get("instrument_type") or "").strip(),
                                  int(float(row.get("lot_size") or 0)), float(row.get("tick_size") or 0)))
        except (KeyError, ValueError):
            continue
    return out


# Kite's NSE dump labels every cash-segment security instrument_type EQ, debt included; the series is the
# tradingsymbol suffix. Equity series only: EQ (no suffix; ETFs trade here too), BE/BZ (trade-for-trade),
# SM/ST (SME platform). Excluded: SG/GS/TB (state and central government securities), N0-N9/NA-NS (NCDs),
# GB (sovereign gold bonds), IV/RR/RL (InvIT/REIT units) and anything unrecognised.
EQUITY_SERIES = ("", "BE", "BZ", "SM", "ST")


def series_of(symbol: str) -> str:
    base, sep, suffix = symbol.rpartition("-")
    return suffix if sep and base and suffix.isalnum() and len(suffix) <= 2 and suffix.isupper() else ""


def select(instruments: list[Instrument]) -> list[Instrument]:
    """Every NSE equity-series instrument plus the named indices, ordered indices -> EQ -> BE/BZ -> SME so that an
    interrupted run still holds the most useful part. Derivatives, debt and other segments are excluded."""
    eq = [i for i in instruments if i.segment == "NSE" and i.kind == "EQ" and series_of(i.symbol) in EQUITY_SERIES]
    idx = [i for i in instruments if i.segment == "INDICES" and i.symbol.upper() in INDEX_NAMES]
    order = {s: n for n, s in enumerate(EQUITY_SERIES)}
    seen, out = set(), []
    for i in idx + sorted(eq, key=lambda i: (order[series_of(i.symbol)], i.symbol)):
        if i.token not in seen:
            seen.add(i.token)
            out.append(i)
    return out


def chunks(end: date, earliest: date = EARLIEST, span: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    """Newest first: [(from, to), ...], each at most ``span`` calendar days, covering earliest..end."""
    out, hi = [], end
    while hi >= earliest:
        lo = max(earliest, hi - timedelta(days=span - 1))
        out.append((lo, hi))
        hi = lo - timedelta(days=1)
    return out


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.done: dict[tuple[int, str, str], dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.done[(int(r["token"]), r["from"], r["to"])] = r

    def has(self, token: int, lo: date, hi: date) -> dict | None:
        return self.done.get((token, lo.isoformat(), hi.isoformat()))

    def add(self, rec: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self.done[(int(rec["token"]), rec["from"], rec["to"])] = rec


def _fetch(client, token: int, lo: date, hi: date, sleep=time.sleep, retries: int = 3):
    start = datetime(lo.year, lo.month, lo.day, 0, 0, tzinfo=IST).strftime("%Y-%m-%d %H:%M:%S")
    end = datetime(hi.year, hi.month, hi.day, 23, 59, tzinfo=IST).strftime("%Y-%m-%d %H:%M:%S")
    for attempt in range(retries + 1):
        try:
            return client.history(token, "day", start, end)
        except AuthenticationRequired:
            raise
        except KiteError as e:
            if "429" in str(e) and attempt < retries:
                sleep(30)
                continue
            raise


def download(client, out: Path, *, today: date | None = None, earliest: date = EARLIEST, limit: int | None = None,
             progress=None, sleep=time.sleep, instruments_text: str | None = None) -> dict:
    """Download (or resume) everything. Returns a summary with counts only (no provider bodies, no secrets)."""
    today = today or now().date()
    out.mkdir(parents=True, exist_ok=True)
    if instruments_text is None:
        instruments_text = client.get("/instruments/NSE")
    raw = instruments_text.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    dump = out / "instruments" / f"NSE-{today.isoformat()}.csv"
    if not dump.exists():
        dump.parent.mkdir(parents=True, exist_ok=True)
        dump.write_bytes(raw)
    chosen = select(parse_instruments(instruments_text))
    atomic_json(out / "instruments" / f"selected-{today.isoformat()}.json",
                {"dump_sha256": sha, "count": len(chosen), "instruments": [i.to_json() for i in chosen], **METADATA})
    man = Manifest(out / "manifest.jsonl")
    stats = {"instruments": len(chosen), "requests": 0, "chunks_skipped": 0, "candles": 0, "empty_stops": 0,
             "errors": {}, "stopped": None, "dump_sha256": sha}
    for n, ins in enumerate(chosen[:limit] if limit else chosen, 1):
        for lo, hi in chunks(today, earliest):
            prior = man.has(ins.token, lo, hi)
            if prior is not None:
                stats["chunks_skipped"] += 1
                if prior["candles"] == 0:
                    break
                continue
            try:
                data = _fetch(client, ins.token, lo, hi, sleep=sleep)
            except AuthenticationRequired:
                stats["stopped"] = "SESSION_EXPIRED"
                return stats
            except KiteError as e:
                label = str(e).split(";")[0][:60]
                stats["errors"][label] = stats["errors"].get(label, 0) + 1
                break
            stats["requests"] += 1
            candles = (data or {}).get("candles") or []
            body = json.dumps({"token": ins.token, "symbol": ins.symbol, "from": lo.isoformat(), "to": hi.isoformat(),
                               "retrieved_at": now().isoformat(), "candles": candles, **METADATA},
                              sort_keys=True, separators=(",", ":")).encode()
            path = out / "day" / str(ins.token) / f"{lo.isoformat()}_{hi.isoformat()}.json"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            man.add({"token": ins.token, "symbol": ins.symbol, "from": lo.isoformat(), "to": hi.isoformat(),
                     "candles": len(candles), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "retrieved_at": now().isoformat()})
            stats["candles"] += len(candles)
            if not candles:  # passed the listing date: nothing older exists for this instrument
                stats["empty_stops"] += 1
                break
        if progress and (n % 25 == 0 or n == len(chosen)):
            progress(f"{n}/{len(chosen)} instruments · {stats['requests']} requests · {stats['candles']:,} candles"
                     f" · {sum(stats['errors'].values())} errors")
    stats["stopped"] = stats["stopped"] or "COMPLETE"
    atomic_json(out / "summary.json", stats | {"finished_at": now().isoformat()})
    return stats
