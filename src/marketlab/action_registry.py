"""Listed corporate actions from official NSE records, checked against the prices, for labels and the ledger.

NSE's bhavcopy base price (PrvsClsgPric) is NOT adjusted on split or bonus ex-dates (observed for 2025 and on 4 Nov
2026), and a split usually moves the symbol to a new ISIN. A price series therefore cannot reveal an action's ratio;
only a listed action can. This module:

* parses NSE ``PURPOSE`` text ("BONUS 1:1", "FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RE 1/- PER
  SHARE", "INTERIM DIVIDEND - RS 4 PER SHARE", "RIGHTS 3:8 @ PREMIUM RE 0.50/-", "BUY BACK", ...);
* imports two official record types into an append-only store with provenance: the corporate-actions CSV that the
  owner downloads from nseindia.com (Corporate Filings -> Corporate Actions, a date range, Download .csv), and the
  daily RSS feed the scheduler already collects (prospective history);
* maps each record to ISINs (symbol, or the company name printed in the bhavcopy) on the session before the
  ex-date, following an ISIN succession on the ex-date;
* checks every split/bonus ratio against the jump actually observed: close / unadjusted base divided by the listed
  factor must look like an ordinary session (0.8-1.25), otherwise the action is RATIO_INCONSISTENT and not used.

Labels then apply a consistent listed factor exactly once (and follow the successor ISIN); the ledger restates units
and re-keys the holding. Dividends are recorded, not added to price labels: the benchmark is a price index, and a
total-return label against a price benchmark would mix conventions (review); the ledger books them as receivables
with an unknown payment date.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .store import Store

KIND = "corporate_action"
RS = r"R[SE]\.?\s*"
NUM = r"(\d+(?:\.\d+)?)"
CONSISTENT_LOW, CONSISTENT_HIGH = 0.8, 1.25


def parse_purpose(text: str) -> list[dict]:
    """Every action named in one NSE purpose string. Unknown wording gives kind UNPARSED (never guessed)."""
    t = re.sub(r"\s+", " ", (text or "").upper()).strip()
    out = []
    for m in re.finditer(r"BONUS\s*" + r"(\d+)\s*:\s*(\d+)", t):
        new, held = int(m.group(1)), int(m.group(2))
        out.append({"kind": "BONUS", "ratio_new": new, "ratio_held": held, "price_factor": held / (held + new)})
    for m in re.finditer(r"(?:SPLIT|SUB-DIVISION|CONSOLIDATION).*?FROM\s*" + RS + NUM + r"[/\- ]*(?:PER SHARE)?\s*TO\s*" + RS + NUM, t):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0:
            out.append({"kind": "SPLIT" if new < old else "CONSOLIDATION", "old_fv": old, "new_fv": new,
                        "price_factor": new / old})
    for m in re.finditer(r"((?:INTERIM|FINAL|SPECIAL)\s*)?DIVIDEND\s*-?\s*" + RS + NUM + r"\s*PER SHARE", t):
        out.append({"kind": "DIVIDEND", "label": (m.group(1) or "").strip() or "DIVIDEND", "cash_per_share": float(m.group(2))})
    for m in re.finditer(r"RIGHTS\s*(\d+)\s*:\s*(\d+)(?:\s*@\s*PREMIUM\s*" + RS + NUM + r")?", t):
        out.append({"kind": "RIGHTS", "ratio_new": int(m.group(1)), "ratio_held": int(m.group(2)),
                    "premium": float(m.group(3)) if m.group(3) else None})
    if "BUY BACK" in t or "BUYBACK" in t:
        out.append({"kind": "BUYBACK"})
    for word, kind in (("DEMERGER", "DEMERGER"), ("SCHEME OF ARRANGEMENT", "SCHEME"), ("AMALGAMATION", "SCHEME"),
                       ("CAPITAL REDUCTION", "CAPITAL_REDUCTION"), ("REDUCTION OF CAPITAL", "CAPITAL_REDUCTION")):
        if word in t:
            out.append({"kind": kind})
    if not out:
        out.append({"kind": "UNPARSED"})
    return out


def _date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _norm_name(s: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    s = re.sub(r"\bLTD\b", "LIMITED", s)
    return re.sub(r"\s+", " ", s).strip()


def _record(source, sha, received_at, *, ex_date, purpose, series=None, symbol=None, company=None, record_date=None,
            face_value=None, published_at=None) -> dict:
    return {"source": source, "source_sha256": sha, "received_at": received_at, "published_at": published_at,
            "symbol": symbol, "company": company, "series": series, "ex_date": ex_date.isoformat(),
            "record_date": record_date.isoformat() if record_date else None, "face_value": face_value,
            "purpose": purpose, "parsed": parse_purpose(purpose)}


def ingest_rss(store: Store, raw: bytes, *, sha256: str, received_at: str) -> list[dict]:
    """Items of NSE's Corporate_action.xml feed (title 'Company - Ex-Date: DD-Mon-YYYY', description fields)."""
    import xml.etree.ElementTree as ET
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("feed with a DOCTYPE or entity is refused")
    out = []
    for item in ET.fromstring(raw).findall(".//item"):
        title = (item.findtext("title") or "").strip()
        company, _, rest = title.partition(" - Ex-Date:")
        ex = _date(rest)
        fields = dict((k.strip().upper(), v.strip()) for k, _, v in
                      (p.partition(":") for p in (item.findtext("description") or "").split("|")) if k.strip())
        if not ex or not fields.get("PURPOSE"):
            continue
        pub = (item.findtext("pubDate") or "").strip()
        try:
            pub_iso = datetime.strptime(pub, "%d-%b-%Y %H:%M:%S").isoformat() + "+05:30"
        except ValueError:
            pub_iso = None
        rec = _record("NSE_RSS_CORPORATE_ACTIONS", sha256, received_at, ex_date=ex, purpose=fields["PURPOSE"],
                      series=fields.get("SERIES"), company=company.strip(), record_date=_date(fields.get("RECORD DATE", "")),
                      face_value=fields.get("FACE VALUE"), published_at=pub_iso)
        store.append(KIND, "nse:rss", f"{rec['ex_date']}|{_norm_name(rec['company'])}|{rec['purpose']}", rec,
                     published_at=pub_iso, received_at=received_at)
        out.append(rec)
    return out


CSV_COLUMNS = {"SYMBOL": "symbol", "COMPANY NAME": "company", "COMPANY": "company", "SERIES": "series", "PURPOSE": "purpose",
               "FACE VALUE": "face_value", "EX-DATE": "ex_date", "EX DATE": "ex_date", "RECORD DATE": "record_date"}


def import_nse_csv(store: Store, path: Path, *, received_at: str) -> dict:
    """The corporate-actions CSV downloaded by the owner from nseindia.com. Headers are matched by name (SYMBOL,
    PURPOSE and EX-DATE are required); a row without a parseable ex-date or purpose is counted, not guessed."""
    import hashlib
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise ValueError("empty file")
    head = [CSV_COLUMNS.get(h.strip().strip('"').upper()) for h in rows[0]]
    if not {"symbol", "purpose", "ex_date"} <= set(head):
        raise ValueError(f"unrecognised header: {rows[0]}")
    stored, skipped = 0, 0
    for r in rows[1:]:
        f = {k: v.strip() for k, v in zip(head, r) if k}
        ex = _date(f.get("ex_date", ""))
        if not ex or not f.get("purpose") or not f.get("symbol"):
            skipped += 1
            continue
        rec = _record("NSE_CORPORATE_ACTIONS_CSV", sha, received_at, ex_date=ex, purpose=f["purpose"], series=f.get("series"),
                      symbol=f["symbol"].upper(), company=f.get("company"), record_date=_date(f.get("record_date", "")),
                      face_value=f.get("face_value"))
        store.append(KIND, "nse:csv", f"{rec['ex_date']}|{rec['symbol']}|{rec['purpose']}", rec, received_at=received_at)
        stored += 1
    return {"file_sha256": sha, "rows": len(rows) - 1, "stored": stored, "skipped": skipped}


def records(store: Store) -> list[dict]:
    rows = store.db.execute("SELECT payload FROM observations WHERE kind = ?", (KIND,)).fetchall()
    import json
    return [json.loads(r[0]) for r in rows]


@dataclass
class ListedAction:
    isin: str
    ex_date: date
    kinds: list[str]
    price_factor: float | None  # split/bonus/consolidation product; None when none or unusable
    dividend_cash: float
    status: str  # RATIO_CONSISTENT | RATIO_INCONSISTENT | NO_PRICE_FACTOR | NO_BAR_ON_EX_DATE
    observed_ratio: float | None
    successor_isin: str | None
    sources: list[str] = field(default_factory=list)


class ActionIndex:
    """Listed actions keyed by (ISIN, ex-date), mapped and checked against one panel."""

    def __init__(self, panel, recs: list[dict]):
        self.by_key: dict[tuple[str, date], ListedAction] = {}
        self.unmapped: list[dict] = []
        disc = panel.discontinuities()
        succ = {(i, d): v[2] for i, dd in disc.items() for d, vs in dd.items() for v in vs if v[0] == "IDENTITY_END"}
        sessions = panel.sessions()
        for rec in recs:
            ex = date.fromisoformat(rec["ex_date"])
            before = [d for d in sessions if d < ex]
            if not before:
                self.unmapped.append(rec | {"why": "NO_SESSION_BEFORE_EX_DATE"})
                continue
            prev = before[-1]
            isins = self._match(panel, prev, rec)
            if not isins:
                self.unmapped.append(rec | {"why": "NO_ISIN_MATCH"})
                continue
            for isin in isins:
                self._add(panel, isin, ex, rec, succ.get((isin, ex)))

    @staticmethod
    def _match(panel, day: date, rec: dict) -> list[str]:
        rows = panel.db.execute("SELECT isin, symbol, series, name FROM bars WHERE day = ?", (day.isoformat(),)).fetchall()
        series = (rec.get("series") or "EQ").upper()
        if rec.get("symbol"):
            return [i for i, sym, ser, _ in rows if sym == rec["symbol"] and (ser or "") == series]
        want = _norm_name(rec.get("company") or "")
        return [i for i, _, ser, name in rows if _norm_name(name) == want and (ser or "") == series] if want else []

    def _add(self, panel, isin: str, ex: date, rec: dict, successor: str | None):
        key = (isin, ex)
        la = self.by_key.get(key) or ListedAction(isin, ex, [], None, 0.0, "NO_PRICE_FACTOR", None, successor)
        for p in rec["parsed"]:
            if p["kind"] in la.kinds and p["kind"] != "DIVIDEND":
                continue  # the same action from two sources (CSV and feed) is applied once
            la.kinds.append(p["kind"])
            if p.get("price_factor"):
                la.price_factor = (la.price_factor or 1.0) * p["price_factor"]
            if p["kind"] == "DIVIDEND":
                la.dividend_cash += p["cash_per_share"]
        la.sources.append(rec["source"])
        bar_isin = successor or isin
        bars = panel.bars(bar_isin, ex, ex)
        if la.price_factor:
            if not bars or not bars[0].prev_close:
                la.status = "NO_BAR_ON_EX_DATE"
            else:
                la.observed_ratio = bars[0].close / bars[0].prev_close
                implied = panel.implied_factors(bar_isin, ex, ex).get(ex)
                base_adjusted = implied is not None and abs(implied - la.price_factor) < 0.01
                # with an unadjusted base the jump is the factor times an ordinary day; with an adjusted base the
                # close/base ratio is an ordinary day by itself (the factor shows as the implied factor instead)
                residual = la.observed_ratio if base_adjusted else la.observed_ratio / la.price_factor
                la.status = "RATIO_CONSISTENT" if CONSISTENT_LOW <= residual <= CONSISTENT_HIGH else "RATIO_INCONSISTENT"
        self.by_key[key] = la

    def get(self, isin: str, day: date) -> ListedAction | None:
        return self.by_key.get((isin, day))

    def factor(self, isin: str, day: date) -> float | None:
        """The price factor to apply on ``day`` (consistent splits/bonuses only), else None."""
        la = self.by_key.get((isin, day))
        return la.price_factor if la and la.status == "RATIO_CONSISTENT" else None

    def days_for(self, isin: str) -> set[date]:
        return {d for (i, d), la in self.by_key.items() if i == isin}

    def summary(self) -> dict:
        from collections import Counter
        return {"mapped": len(self.by_key), "unmapped": len(self.unmapped),
                "by_status": dict(Counter(la.status for la in self.by_key.values())),
                "by_kind": dict(Counter(k for la in self.by_key.values() for k in la.kinds))}


def registry_path(market: Path) -> Path:
    return market / "actions.sqlite3"


def load_index(market: Path, panel) -> ActionIndex | None:
    """The ActionIndex for this market folder's registry, or None when no record was ever imported."""
    path = registry_path(market)
    if not path.exists() or panel is None:
        return None
    store = Store(path)
    try:
        recs = records(store)
    finally:
        store.close()
    return ActionIndex(panel, recs) if recs else None


def ingest_stored_feeds(market: Path) -> dict:
    """Every stored vintage of NSE's corporate-action RSS feed into the registry (idempotent: identical records
    are stored once). This builds the listed-action history forward from the day collection started."""
    import gzip
    import hashlib
    from . import sources
    folder = market / "raw" / "nse_rss_corporate_actions"
    store = Store(registry_path(market))
    n = files = 0
    try:
        for p in sorted(folder.glob("*.gz")) if folder.exists() else []:
            raw = gzip.decompress(p.read_bytes())
            rec = sources.stored(market, "nse_rss_corporate_actions", date.fromisoformat(p.name.split(".")[0]))
            received = (rec or {}).get("received_at") or (rec or {}).get("available_at")
            n += len(ingest_rss(store, raw, sha256=hashlib.sha256(raw).hexdigest(), received_at=received))
            files += 1
    finally:
        store.close()
    return {"feed_files": files, "items": n}
