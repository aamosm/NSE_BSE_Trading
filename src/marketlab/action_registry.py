"""Listed corporate actions from official NSE records, checked against the prices, for labels, features and the ledger.

NSE's bhavcopy base price (PrvsClsgPric) is NOT adjusted on split or bonus ex-dates (observed for 2025 and on 4 Nov
2026), and a split usually moves the symbol to a new ISIN. A price series therefore cannot reveal an action's ratio;
only a listed action can. This module:

* parses NSE ``PURPOSE``/``subject`` text ("BONUS 1:1", "FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO
  RE 1/- PER SHARE", "FV SPLT FRM RS 10 TO RS 2", "Interim Dividend - Rs 5/- Per Share", "Final Dividend Rs 6/- Plus
  Special Dividend Rs 4/- Per Share", "RIGHTS 3:8 @ PREMIUM RE 0.50/-", "BUY BACK", "ANNUAL GENERAL MEETING", ...).
  Wording it does not recognise is kind UNPARSED, never guessed; meetings and book closures are NON-PRICE kinds;
* imports three official record types into an append-only store with provenance: the corporate-actions CSV the owner
  downloads from nseindia.com, the daily RSS feed the scheduler collects (prospective history), and the JSON of NSE's
  date-ranged corporate-actions API (``/api/corporates-corporateActions``), verified file by file against the
  manifest that recorded each response's SHA-256 at receipt;
* maps each record to ISINs (symbol + series, or the company name printed in the bhavcopy) on the session before the
  ex-date, following an ISIN succession on the ex-date. The API also prints an ISIN, but it is the company's ISIN at
  the time of the API response (after a split it is the NEW ISIN), so it is kept for comparison, not used to map;
* checks every split/bonus ratio against the jump actually observed: close / unadjusted base divided by the listed
  factor must look like an ordinary session (0.8-1.25), otherwise the action is RATIO_INCONSISTENT and not used;
* deduplicates: the same action from several sources or vintages is applied once; a "(PURPOSE REVISED)" record
  supersedes the original's dividend amounts for that ex-date.

Labels then apply a consistent listed factor exactly once (and follow the successor ISIN); features use it to correct
the ex-date return and to put earlier prices in post-action units; the ledger restates units and re-keys the holding.
Dividends are recorded, not added to price labels: the benchmark is a price index, and a total-return label against a
price benchmark would mix conventions (review); the ledger books them as receivables with an unknown payment date.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .store import Store

KIND = "corporate_action"
RS = r"R[SE]\.?\s*"
NUM = r"(\d+(?:\.\d+)?)"
CONSISTENT_LOW, CONSISTENT_HIGH = 0.8, 1.25
FACTOR_KINDS = ("BONUS", "SPLIT", "CONSOLIDATION")  # kinds with a price factor the prices can be checked against
UNPRICED_KINDS = ("RIGHTS", "DEMERGER", "SCHEME", "CAPITAL_REDUCTION", "BUYBACK", "BONUS_OTHER_SECURITY")  # move prices; no factor here
NON_PRICE_KINDS = ("AGM", "EGM", "BOOK_CLOSURE")  # meetings and register closures: no price effect by themselves
API_SOURCE = "NSE_CORPORATE_ACTIONS_API"

_DIVIDEND = re.compile(r"((?:INTERIM|FINAL|SPECIAL|SPL|INT)\s*)?DIV(?:IDEND)?\b\s*[-:*\ufffd]?\s*(?:OF\s*)?"
                       r"((?:(?:RS|RE|R E|INR)\s*\.?\s*[-*\ufffd]?\s*)+)?(\d+(?:\.\d+)?)?\s*(/-|%)?")
_AGM = re.compile(r"\bA\w{3,6}L\s+G\w{5,7}\s+ME\w{3,6}\b|\bAGM\b")  # tolerates the typos in NSE's wording
_SPLIT = re.compile(r"(?:SPLIT|SPLT|SUB-DIVISION|SUBDIVISION|SUB DIVISION|CONSOLIDATION).*?FR(?:O)?M\s*" + RS + NUM
                    + r"[/\- ]*(?:PER SHARE)?(?:\s*EACH)?\s*TO\s*" + RS + NUM)


def parse_purpose(text: str) -> list[dict]:
    """Every action named in one NSE purpose string. Unknown wording gives kind UNPARSED (never guessed)."""
    t = re.sub(r"\s+", " ", (text or "").upper()).strip()
    out = []
    if re.search(r"BONUS\s*[-:]?\s*(?:NCRPS|PREFERENCE|DEBENTURE|\d+\s*DEBENTURE)", t):
        out.append({"kind": "BONUS_OTHER_SECURITY"})  # preference shares or debentures: no equity price factor
    for m in re.finditer(r"BONUS\s*[-:]?\s*(?:ISSUE\s*)?(?:OF\s*)?(?:SHARES\s*)?(?:IN\s*THE\s*RATIO\s*(?:OF\s*)?)?"
                         r"(\d+)\s*:\s*(\d+)", t):
        new, held = int(m.group(1)), int(m.group(2))
        if new > 0 and held > 0:
            out.append({"kind": "BONUS", "ratio_new": new, "ratio_held": held, "price_factor": held / (held + new)})
    for m in _SPLIT.finditer(t):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and old != new:
            out.append({"kind": "SPLIT" if new < old else "CONSOLIDATION", "old_fv": old, "new_fv": new,
                        "price_factor": new / old})
    for m in _DIVIDEND.finditer(t):
        if "INCLUDING" in t[max(0, m.start() - 14):m.start()]:
            continue  # "(INCLUDING SPECIAL DIVIDEND OF RS 5)" is part of the amount already stated
        label = {"SPL": "SPECIAL", "INT": "INTERIM"}.get((m.group(1) or "").strip(), (m.group(1) or "").strip()) or "DIVIDEND"
        amount, unit = m.group(3), m.group(4)
        tail = t[m.end():m.end() + 24]
        # an amount counts only when it is clearly rupees per share (currency, "PER SH..." or "/-"), or a percentage
        # of face value; anything else (a year, a meeting number) is left unknown rather than read as cash
        rupees = bool(m.group(2)) or unit == "/-" or re.match(r"\s*PER\s*(?:EQUITY\s*)?SH", tail) is not None
        item = {"kind": "DIVIDEND", "label": label, "cash_per_share": None}
        if amount and unit == "%":
            item["percent_of_face_value"] = float(amount)
        elif amount and rupees:
            item["cash_per_share"] = float(amount)
        out.append(item)
    for m in re.finditer(r"RIGHTS\s*(?:ISSUE\s*)?(\d+)\s*:\s*(\d+)(?:\s*@\s*PREMIUM\s*" + RS + NUM + r")?", t):
        out.append({"kind": "RIGHTS", "ratio_new": int(m.group(1)), "ratio_held": int(m.group(2)),
                    "premium": float(m.group(3)) if m.group(3) else None})
    if "BUY BACK" in t or "BUYBACK" in t or "BUY-BACK" in t:
        out.append({"kind": "BUYBACK"})
    for word, kind in (("DEMERGER", "DEMERGER"), ("DE-MERGER", "DEMERGER"), ("SCHEME OF ARRANGEMENT", "SCHEME"), ("SCHEME OF ARANGEMENT", "SCHEME"),
                       ("SHEME OF ARRANGEMENT", "SCHEME"), ("AMALGAMATION", "SCHEME"),
                       ("CAPITAL REDUCTION", "CAPITAL_REDUCTION"), ("REDUCTION OF CAPITAL", "CAPITAL_REDUCTION")):
        if word in t and not any(o["kind"] == kind for o in out):
            out.append({"kind": kind})
    if _AGM.search(t):
        out.append({"kind": "AGM"})
    if re.search(r"EXTRA\s*-?\s*ORDINARY GENERAL MEETING", t):
        out.append({"kind": "EGM"})
    if ("BOOK CLOS" in t or "ANNUAL CLOSING" in t) and not any(o["kind"] in ("AGM", "EGM") for o in out):
        out.append({"kind": "BOOK_CLOSURE"})
    if not out:
        out.append({"kind": "UNPARSED"})
    return out


def is_revised(text: str) -> bool:
    return re.search(r"PURPOSE\w*\s+REVISED", (text or "").upper()) is not None  # also NSE's "PURPOSED REVISED"


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
            face_value=None, published_at=None, **extra) -> dict:
    return {"source": source, "source_sha256": sha, "received_at": received_at, "published_at": published_at,
            "symbol": symbol, "company": company, "series": series, "ex_date": ex_date.isoformat(),
            "record_date": record_date.isoformat() if record_date else None, "face_value": face_value,
            "purpose": purpose, "revised": is_revised(purpose), "parsed": parse_purpose(purpose), **extra}


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


def _dash(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return None if v in (None, "", "-") else v


def import_nse_api_json(store: Store, raw: bytes, *, received_at: str, url: str | None = None,
                        expected_sha256: str | None = None) -> dict:
    """One response of NSE's corporate-actions API (a JSON list of {symbol, series, isin, comp, subject, exDate,
    recDate, faceVal, bcStartDate, bcEndDate, ndStartDate, ndEndDate, caBroadcastDate}). Every field is kept as
    received; ``published_at`` stays unknown unless caBroadcastDate is given (it was null in every 2016-2025 row).
    Exact duplicate rows inside a response are stored once and counted."""
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise ValueError(f"SHA256_MISMATCH: file {sha[:16]} != manifest {expected_sha256[:16]}")
    try:
        rows = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        raise ValueError("not JSON") from None
    if isinstance(rows, dict):
        rows = rows.get("data")
    if not isinstance(rows, list):
        raise ValueError("unexpected JSON shape: expected a list of records")
    seen, stored, skipped, dup = set(), 0, 0, 0
    for r in rows:
        if not isinstance(r, dict):
            skipped += 1
            continue
        ex, subject = _date(r.get("exDate") or ""), re.sub(r"\s+", " ", (r.get("subject") or "")).strip()
        sym, series = (r.get("symbol") or "").strip().upper(), (r.get("series") or "").strip().upper()
        if not ex or not subject or not sym:
            skipped += 1
            continue
        key = (sym, series, ex, subject.upper())
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        broadcast = _dash(r.get("caBroadcastDate"))
        rec = _record(API_SOURCE, sha, received_at, ex_date=ex, purpose=subject, series=series or None, symbol=sym,
                      company=_dash(r.get("comp")), record_date=_date(r.get("recDate") or ""), face_value=_dash(r.get("faceVal")),
                      published_at=None, api_isin=_dash(r.get("isin")), api_url=url,
                      book_closure=[_dash(r.get("bcStartDate")), _dash(r.get("bcEndDate"))],
                      no_delivery=[_dash(r.get("ndStartDate")), _dash(r.get("ndEndDate"))], api_broadcast=broadcast)
        store.append(KIND, "nse:api", f"{rec['ex_date']}|{sym}|{series}|{subject.upper()}", rec, received_at=received_at)
        stored += 1
    return {"file_sha256": sha, "rows": len(rows), "stored": stored, "duplicates_in_response": dup, "skipped": skipped}


def import_verification_folder(store: Store, folder: Path) -> dict:
    """An evidence folder of API responses (raw/YYYY.json + manifest.json with url, received_at and sha256 per file).
    A file whose bytes do not match its manifest hash is refused, not imported."""
    man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    out = {"manifest_sha256": hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest(),
           "source": man.get("source"), "files": []}
    for f in man.get("files", []):
        path = folder / "raw" / f"{f['year']}.json"
        entry = {"year": f["year"], "expected_sha256": f.get("sha256")}
        if not path.exists():
            out["files"].append(entry | {"result": "MISSING"})
            continue
        try:
            res = import_nse_api_json(store, path.read_bytes(), received_at=f.get("received_at"), url=f.get("url"),
                                      expected_sha256=f.get("sha256"))
            out["files"].append(entry | {"result": "IMPORTED", **res})
        except ValueError as e:
            out["files"].append(entry | {"result": str(e).split(":")[0]})
    out["imported_rows"] = sum(x.get("stored", 0) for x in out["files"])
    return out


def records(store: Store) -> list[dict]:
    rows = store.db.execute("SELECT payload FROM observations WHERE kind = ?", (KIND,)).fetchall()
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
    base_adjusted: bool = False  # the exchange base price already carried the factor (the jump is not in close/base)
    dividends: list = field(default_factory=list)  # distinct (label, cash per share) pairs
    api_isins: list = field(default_factory=list)  # ISINs printed by the API for this action (comparison only)
    purposes: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"isin": self.isin, "ex_date": self.ex_date.isoformat(), "kinds": self.kinds, "price_factor": self.price_factor,
                "dividend_cash": self.dividend_cash, "dividends": self.dividends, "status": self.status,
                "observed_ratio": self.observed_ratio, "successor_isin": self.successor_isin, "base_adjusted": self.base_adjusted,
                "sources": sorted(set(self.sources)), "api_isins": self.api_isins, "purposes": self.purposes[:4]}


class ActionIndex:
    """Listed actions keyed by (ISIN, ex-date), mapped and checked against one panel."""

    def __init__(self, panel, recs: list[dict]):
        self.by_key: dict[tuple[str, date], ListedAction] = {}
        self.unmapped: list[dict] = []
        self.out_of_range = 0
        self._maps: dict[date, tuple[dict, dict]] = {}
        disc = panel.discontinuities()
        succ = {(i, d): v[2] for i, dd in disc.items() for d, vs in dd.items() for v in vs if v[0] == "IDENTITY_END"}
        sessions = panel.sessions()
        grouped: dict[tuple[str, date], list[dict]] = {}
        for rec in recs:
            ex = date.fromisoformat(rec["ex_date"])
            pos = bisect.bisect_left(sessions, ex)
            if pos == 0 or ex > sessions[-1]:
                self.out_of_range += 1  # before the panel's second session or after its last: nothing to map or check
                continue
            isins = self._match(panel, sessions[pos - 1], rec)
            if not isins:
                self.unmapped.append(rec | {"why": "NO_ISIN_MATCH"})
                continue
            for isin in isins:
                grouped.setdefault((isin, ex), []).append(rec)
        for (isin, ex), rs in grouped.items():
            self.by_key[(isin, ex)] = self._build(panel, isin, ex, rs, succ.get((isin, ex)))

    def _day_maps(self, panel, day: date):
        if day not in self._maps:
            by_sym, by_name = {}, {}
            for i, sym, ser, name in panel.db.execute("SELECT isin, symbol, series, name FROM bars WHERE day = ?",
                                                      (day.isoformat(),)):
                by_sym.setdefault((sym, ser or ""), []).append(i)
                by_name.setdefault((_norm_name(name), ser or ""), []).append(i)
            self._maps[day] = (by_sym, by_name)
        return self._maps[day]

    def _match(self, panel, day: date, rec: dict) -> list[str]:
        by_sym, by_name = self._day_maps(panel, day)
        series = (rec.get("series") or "EQ").upper()
        if rec.get("symbol"):
            return list(by_sym.get((rec["symbol"], series), []))
        want = _norm_name(rec.get("company") or "")
        return list(by_name.get((want, series), [])) if want else []

    @staticmethod
    def _build(panel, isin: str, ex: date, recs: list[dict], successor: str | None) -> ListedAction:
        la = ListedAction(isin, ex, [], None, 0.0, "NO_PRICE_FACTOR", None, successor)
        # parse again with the current parser (the stored "parsed" field is the parser output at import time)
        parsed = [(rec, parse_purpose(rec.get("purpose") or ""), is_revised(rec.get("purpose") or "")) for rec in recs]
        revised_divs = any(rev and any(p["kind"] == "DIVIDEND" for p in ps) for _, ps, rev in parsed)
        divs = set()
        for rec, ps, rev in sorted(parsed, key=lambda x: (x[0].get("source") or "", x[0].get("purpose") or "")):
            la.sources.append(rec["source"])
            if rec.get("purpose") not in la.purposes:
                la.purposes.append(rec.get("purpose"))
            if rec.get("api_isin") and rec["api_isin"] not in la.api_isins:
                la.api_isins.append(rec["api_isin"])
            for p in ps:
                if p["kind"] == "DIVIDEND":
                    if revised_divs and not rev:
                        continue  # a revised purpose supersedes the original's amounts for this ex-date
                    if p.get("cash_per_share") is not None:
                        divs.add((p["label"], p["cash_per_share"]))
                    if "DIVIDEND" not in la.kinds:
                        la.kinds.append("DIVIDEND")
                    continue
                if p["kind"] in la.kinds:
                    continue  # the same action from two sources (CSV, feed, API) is applied once
                la.kinds.append(p["kind"])
                if p.get("price_factor"):
                    la.price_factor = (la.price_factor or 1.0) * p["price_factor"]
        la.dividends = sorted(divs)
        la.dividend_cash = round(sum(a for _, a in divs), 6)
        bar_isin = successor or isin
        bars = panel.bars(bar_isin, ex, ex)
        if la.price_factor:
            if not bars or not bars[0].prev_close:
                la.status = "NO_BAR_ON_EX_DATE"
            else:
                la.observed_ratio = bars[0].close / bars[0].prev_close
                implied = panel.implied_factors(bar_isin, ex, ex).get(ex)
                la.base_adjusted = implied is not None and abs(implied - la.price_factor) < 0.01
                # with an unadjusted base the jump is the factor times an ordinary day; with an adjusted base the
                # close/base ratio is an ordinary day by itself (the factor shows as the implied factor instead)
                residual = la.observed_ratio if la.base_adjusted else la.observed_ratio / la.price_factor
                la.status = "RATIO_CONSISTENT" if CONSISTENT_LOW <= residual <= CONSISTENT_HIGH else "RATIO_INCONSISTENT"
        return la

    def get(self, isin: str, day: date) -> ListedAction | None:
        return self.by_key.get((isin, day))

    def factor(self, isin: str, day: date) -> float | None:
        """The price factor to apply on ``day`` (consistent splits/bonuses only), else None."""
        la = self.by_key.get((isin, day))
        return la.price_factor if la and la.status == "RATIO_CONSISTENT" else None

    def return_factor(self, isin: str, day: date) -> float | None:
        """The factor that turns close/base into an ordinary session's return: the listed factor when the exchange
        base price was NOT adjusted (the 2024-2026 UDiFF case), None when it was (close/base is already ordinary)."""
        la = self.by_key.get((isin, day))
        return la.price_factor if la and la.status == "RATIO_CONSISTENT" and not la.base_adjusted else None

    def days_for(self, isin: str) -> set[date]:
        if getattr(self, "_by_isin", None) is None or self._by_isin_n != len(self.by_key):
            self._by_isin, self._by_isin_n = {}, len(self.by_key)
            for (i, d) in self.by_key:
                self._by_isin.setdefault(i, set()).add(d)
        return set(self._by_isin.get(isin, ()))

    def for_isins(self, isins, start: date | None = None, end: date | None = None) -> list[ListedAction]:
        want = set(isins)
        return sorted((la for (i, d), la in self.by_key.items() if i in want and (start is None or d >= start)
                       and (end is None or d <= end)), key=lambda la: la.ex_date)

    def summary(self) -> dict:
        api_mismatch = [la for la in self.by_key.values() if la.api_isins
                        and not ({la.isin, la.successor_isin} & set(la.api_isins))]
        return {"mapped": len(self.by_key), "unmapped": len(self.unmapped), "outside_panel_range": self.out_of_range,
                "by_status": dict(Counter(la.status for la in self.by_key.values())),
                "by_kind": dict(Counter(k for la in self.by_key.values() for k in la.kinds)),
                "unmapped_examples": [{k: r.get(k) for k in ("symbol", "company", "series", "ex_date", "purpose")}
                                      for r in self.unmapped[:5]],
                "api_isin_differs_from_traded_isin": len(api_mismatch),
                "api_isin_examples": [{"traded_isin": la.isin, "successor": la.successor_isin, "api_isins": la.api_isins,
                                       "ex_date": la.ex_date.isoformat(), "kinds": la.kinds} for la in api_mismatch[:5]],
                "digest": self.digest()}

    def digest(self) -> str:
        body = json.dumps(sorted([la.isin, la.ex_date.isoformat(), la.kinds, la.price_factor, la.dividend_cash, la.status]
                                 for la in self.by_key.values()), default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:16]


def reconcile(panel, index: ActionIndex | None) -> dict:
    """Every price discontinuity and ISIN succession in the panel against the listed actions: explained by a
    consistent factor, listed but inconsistent, listed as a kind without a factor (rights, demerger, scheme ...),
    or not listed at all. Unlisted jumps stay excluded from labels and break feature windows (never guessed)."""
    disc = panel.discontinuities()
    out = {"PRICE_DISCONTINUITY": Counter(), "IDENTITY_END": Counter()}
    examples: dict[str, list] = {}
    for isin, dd in disc.items():
        for d, vs in dd.items():
            for kind, ratio, other in vs:
                if kind not in out:
                    continue
                key = isin
                if kind == "PRICE_DISCONTINUITY":
                    # the jump of a new ISIN's first day belongs to the action listed under its predecessor
                    starts = [o for k2, _, o in vs if k2 == "IDENTITY_START"]
                    if starts:
                        key = starts[0]
                la = index.get(key, d) if index else None
                if la is None:
                    cls = "UNLISTED"
                elif la.status == "RATIO_CONSISTENT":
                    cls = "EXPLAINED_BY_LISTED_FACTOR"
                elif la.status == "RATIO_INCONSISTENT":
                    cls = "LISTED_RATIO_INCONSISTENT"
                elif any(k in UNPRICED_KINDS for k in la.kinds):
                    cls = "LISTED_KIND_WITHOUT_FACTOR"
                else:
                    cls = "LISTED_OTHER"
                out[kind][cls] += 1
                ex = examples.setdefault(f"{kind}:{cls}", [])
                if len(ex) < 5:
                    ex.append({"isin": isin, "day": d.isoformat(), "ratio": ratio, "other_isin": other,
                               "listed": la.to_json() if la else None})
    return {k: dict(v) for k, v in out.items()} | {"examples": examples}


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
