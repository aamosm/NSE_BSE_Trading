"""Bounded historical pilot: official acquisition, provenance, observed sessions, immutable manifests.

Three times are never mixed for a historical file:
* ``received_at``: when THIS system received it (actual local receipt; for a backfill, today). Never backdated.
* ``server_last_modified``: the exchange server's Last-Modified header at receipt (evidence of original
  publication, not proof: a file re-uploaded later carries the later time).
* ``reconstructed_available_at``: what a historical replay may assume. It is the server time when that time lies
  within four days after the file's date, otherwise UNKNOWN. Nothing in the code invents an availability time.

Sessions in a year without a loaded exchange calendar are reconstructed from what the exchange published
(``ObservedCalendar``): a stored bhavcopy is a session, a 404 is a closure, anything else is unknown. That basis is
OBSERVED_PUBLICATION, which is not a verified calendar until the year's holiday circular is checked.

Manifests are written once (exclusive create) and carry their own SHA-256; ``verify_manifest`` re-hashes every
stored file against it.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import time as _time
import zipfile
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import sources
from .common import IST, now, timestamp
from .rules.types import RuleUnknown

PILOT_SOURCES = ("nse_bhavcopy", "nse_indices_close", "nse_sec_list", "nse_reg_indicators")
DOCUMENT_PREFIXES = ("https://nsearchives.nseindia.com/corporate/", "https://nsearchives.nseindia.com/content/circulars/")
MAX_PUBLICATION_LAG = timedelta(days=4)


# ---- acquisition ----------------------------------------------------------------------------------------

def acquire(market: Path, start: date, end: date, ids=PILOT_SOURCES, *, pause=sources.PAUSE_SECONDS, progress=print) -> dict:
    """One attempt per file per date through the registered collector (idempotent: stored files are skipped).
    Weekdays: every source. Weekends: the bhavcopy only (special sessions such as a Budget Saturday), then the
    other sources if a session is found."""
    counts: dict[str, int] = {}
    d = start
    while d <= end:
        if d.weekday() < 5:
            out = sources.collect(market, d, list(ids), pause=pause)
        else:
            out = sources.collect(market, d, ["nse_bhavcopy"], pause=pause)
            if any(r["result"] in ("STORED", "ALREADY_STORED") for r in out):
                out += sources.collect(market, d, [i for i in ids if i != "nse_bhavcopy"], pause=pause)
        for r in out:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
        if progress and d.day == 1:
            progress(f"{d}: {counts}")
        d += timedelta(days=1)
    return counts


def attempts(market: Path) -> dict[str, dict[str, dict]]:
    """{source: {key: latest attempt}} with the receipt and server times kept apart."""
    db = sources.catalog(market)
    try:
        rows = db.db.execute("SELECT o.source, o.subject, o.payload, o.published_at, r.received_at FROM observations o "
                             "JOIN receipts r ON r.observation_id = o.id WHERE o.kind = 'source_file'").fetchall()
    finally:
        db.close()
    out: dict[str, dict[str, dict]] = {}
    for source, key, payload, published, received in rows:
        p = json.loads(payload)
        name = source.removeprefix("public:")
        prev = out.setdefault(name, {}).get(key)
        if prev is None or received > prev["received_at"] or (p.get("result") == "STORED" and prev["result"] != "STORED"):
            out[name][key] = {**p, "received_at": received, "server_published_at": published}
    return out


def availability(source: str, key: str, rec: dict) -> dict:
    """The three separate times for one stored file (see the module docstring)."""
    lm = rec.get("last_modified")
    server = None
    if lm:
        try:
            server = parsedate_to_datetime(lm).astimezone(IST)
        except (TypeError, ValueError):
            server = None
    d = date.fromisoformat(key)
    basis, recon = "NO_SERVER_TIME", None
    if server is not None:
        if d <= server.date() <= d + MAX_PUBLICATION_LAG:
            basis, recon = "SERVER_LAST_MODIFIED", server
        else:
            basis = "SERVER_TIME_OUTSIDE_EXPECTED_WINDOW"
    return {"received_at": rec.get("received_at"), "server_last_modified": server.isoformat() if server else None,
            "reconstructed_available_at": recon.isoformat() if recon else None, "availability_basis": basis}


# ---- sessions reconstructed from publication -------------------------------------------------------------

class ObservedCalendar:
    """Sessions in [start, end] from the bhavcopy attempts: STORED = session, NOT_PUBLISHED (404) = closed,
    anything else = unknown (RuleUnknown). Outside the window it defers to ``fallback`` if given."""
    basis = "OBSERVED_PUBLICATION"

    def __init__(self, market: Path, start: date, end: date, fallback=None):
        self.start, self.end, self.fallback = start, end, fallback
        recs = attempts(market).get("nse_bhavcopy", {})
        self.sessions, self.closed = set(), set()
        for k, r in recs.items():
            d = date.fromisoformat(k)
            if not start <= d <= end:
                continue
            if r.get("result") == "STORED":
                self.sessions.add(d)
            elif r.get("result") == "NOT_PUBLISHED":
                self.closed.add(d)
        self.unknown = set()
        d = start
        while d <= end:
            if d not in self.sessions and d not in self.closed and d.weekday() < 5:
                self.unknown.add(d)
            d += timedelta(days=1)

    def _in(self, d):
        return self.start <= d <= self.end

    def covers(self, exchange, d):
        return self._in(d) or bool(self.fallback and self.fallback.covers(exchange, d))

    def is_trading_day(self, exchange, d):
        if not self._in(d):
            if self.fallback:
                return self.fallback.is_trading_day(exchange, d)
            raise RuleUnknown(f"{d} outside the observed window")
        if d in self.sessions:
            return True
        if d in self.closed or d.weekday() >= 5:
            return False
        raise RuleUnknown(f"{d}: no bhavcopy attempt recorded (session unknown)")

    def is_special_session(self, exchange, d):
        return self._in(d) and d in self.sessions and d.weekday() >= 5

    def session_open(self, exchange, d):
        return time(9, 0) if self.is_trading_day(exchange, d) else None  # regular pre-open start (assumed for weekends)

    def next_trading_day(self, exchange, d):
        n = d + timedelta(days=1)
        while not self.is_trading_day(exchange, n):
            n += timedelta(days=1)
        return n

    def previous_trading_day(self, exchange, d):
        p = d - timedelta(days=1)
        while not self.is_trading_day(exchange, p):
            p -= timedelta(days=1)
        return p

    def report(self) -> dict:
        return {"basis": self.basis, "window": [self.start.isoformat(), self.end.isoformat()],
                "sessions": len(self.sessions), "weekday_closures": sorted(d.isoformat() for d in self.closed if d.weekday() < 5),
                "weekend_sessions": sorted(d.isoformat() for d in self.sessions if d.weekday() >= 5),
                "unknown_weekdays": sorted(d.isoformat() for d in self.unknown)}


# ---- manifest ----------------------------------------------------------------------------------------

def _runs(days: list[date]) -> list[list[str]]:
    """Contiguous runs (by calendar day order) of a sorted date list."""
    out = []
    for d in days:
        if out and (d - date.fromisoformat(out[-1][1])).days <= 3:
            out[-1][1] = d.isoformat()
        else:
            out.append([d.isoformat(), d.isoformat()])
    return out


def build_manifest(market: Path, pilot_id: str, start: date, end: date, ids=PILOT_SOURCES, extra: dict | None = None) -> dict:
    att = attempts(market)
    cal = ObservedCalendar(market, start, end)
    files, missing = {}, {}
    for sid in ids:
        files[sid] = {}
        miss = []
        for k, r in sorted(att.get(sid, {}).items()):
            d = date.fromisoformat(k)
            if not start <= d <= end:
                continue
            files[sid][k] = {"result": r.get("result"), "http_status": r.get("http_status"), "url": r.get("url"),
                             "sha256": r.get("sha256"), "bytes": r.get("bytes"), "path": r.get("path"),
                             **availability(sid, k, r)}
        for d in sorted(cal.sessions):  # a session for which this source is not stored is a missing interval
            if files[sid].get(d.isoformat(), {}).get("result") != "STORED":
                miss.append(d)
        missing[sid] = {"sessions_missing": len(miss), "intervals": _runs(miss)}
    body = {"pilot_id": pilot_id, "window": [start.isoformat(), end.isoformat()], "created_at": now().isoformat(),
            "sources": list(ids), "calendar": cal.report(), "files": files, "missing": missing,
            "rule": "received_at is actual local receipt; reconstructed_available_at is the server Last-Modified when "
                    "within 4 days of the file date, else unknown", **(extra or {})}
    body["content_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def write_once(path: Path, value: dict) -> str:
    """Exclusive create; an existing file is never replaced. Returns the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(market: Path, man: dict) -> list[str]:
    problems = []
    for sid, recs in man["files"].items():
        for k, r in recs.items():
            if r["result"] != "STORED":
                continue
            p = market / r["path"]
            if not p.exists():
                problems.append(f"MISSING_FILE {sid} {k}")
            elif hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest() != r["sha256"]:
                problems.append(f"HASH_MISMATCH {sid} {k}")
    body = {k: v for k, v in man.items() if k != "content_sha256"}
    if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != man.get("content_sha256"):
        problems.append("MANIFEST_CONTENT_HASH_MISMATCH")
    return problems


# ---- the bhavcopy format transition (legacy CSV -> UDiFF, July 2024) ---------------------------------------

LEGACY_MAP = {"ISIN": "ISIN", "SYMBOL": "TckrSymb", "SERIES": "SctySrs", "OPEN": "OpnPric", "HIGH": "HghPric",
              "LOW": "LwPric", "CLOSE": "ClsPric", "LAST": "LastPric", "PREVCLOSE": "PrvsClsgPric",
              "TOTTRDQTY": "TtlTradgVol", "TOTTRDVAL": "TtlTrfVal", "TOTALTRADES": "TtlNbOfTxsExctd"}


def parse_legacy_bhavcopy(raw: bytes) -> list[dict]:
    """Legacy NSE CM bhavcopy rows renamed to the UDiFF columns the panel reads. The legacy file has no security
    name (FinInstrmNm is left empty, so ETF detection falls back to the INF ISIN prefix)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        (name,) = z.namelist()
        text = z.read(name).decode("utf-8-sig")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items() if k}
        out.append({u: r.get(l, "") for l, u in LEGACY_MAP.items()} | {"FinInstrmNm": ""})
    return out


def format_transition(market: Path, day: date) -> dict:
    """Compare the legacy and UDiFF files of the same session field by field (ISIN + series join)."""
    from .master import parse_bhavcopy
    leg, new = sources.read_raw(market, "nse_bhavcopy_legacy", day), sources.read_raw(market, "nse_bhavcopy", day)
    if not leg or not new:
        return {"day": day.isoformat(), "comparable": False, "legacy": bool(leg), "udiff": bool(new)}
    a = {(r["ISIN"], r["SctySrs"]): r for r in parse_legacy_bhavcopy(leg)}
    b = {(r.get("ISIN"), r.get("SctySrs")): r for r in parse_bhavcopy(new, zipped=True) if r.get("SctySrs") and r.get("ISIN")}
    both = sorted(set(a) & set(b))
    fields = ["OpnPric", "HghPric", "LwPric", "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd"]
    mism = {f: 0 for f in fields}
    examples = []
    for k in both:
        for f in fields:
            try:
                x, y = float(a[k][f]), float(b[k][f])
            except (TypeError, ValueError):
                mism[f] += 1
                continue
            tol = 0.5 if f == "TtlTrfVal" else 1e-6  # traded value may differ by paisa rounding
            if abs(x - y) > tol * max(1.0, abs(y)) * (1e-6 if f == "TtlTrfVal" else 1):
                mism[f] += 1
                if len(examples) < 5:
                    examples.append({"isin": k[0], "series": k[1], "field": f, "legacy": x, "udiff": y})
    eq = lambda keys: sum(1 for k in keys if k[1] == "EQ")  # noqa: E731
    return {"day": day.isoformat(), "comparable": True, "rows_legacy": len(a), "rows_udiff_with_series": len(b),
            "joined": len(both), "joined_eq": eq(both), "only_legacy": len(set(a) - set(b)), "only_udiff": len(set(b) - set(a)),
            "only_legacy_eq": eq(set(a) - set(b)), "only_udiff_eq": eq(set(b) - set(a)),
            "mismatches": mism, "examples": examples,
            "legacy_lacks": ["FinInstrmNm", "FinInstrmTp", "FinInstrmId", "TradDt (TIMESTAMP instead)"]}


# ---- exchange-hosted documents (filings) -------------------------------------------------------------

def fetch_document(folder: Path, url: str, *, fetch=sources.http_fetch) -> dict:
    """One request for an exchange-hosted document; stored with its receipt record. A stored document is reused."""
    if not url.startswith(DOCUMENT_PREFIXES):
        raise ValueError("only exchange-hosted corporate documents")
    name = url.rsplit("/", 1)[-1]
    meta_path = folder / (name + ".json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    received = now()
    status, body, modified = fetch(url)
    rec = {"url": url, "http_status": status, "received_at": received.isoformat(), "server_last_modified": modified,
           "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest() if body else None}
    if status == 200 and body:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + ".gz")).write_bytes(gzip.compress(body, mtime=0))
    write_once(meta_path, rec)
    return rec


def read_document(folder: Path, url: str) -> bytes | None:
    p = folder / (url.rsplit("/", 1)[-1] + ".gz")
    return gzip.decompress(p.read_bytes()) if p.exists() else None



# ---- exchange circulars: the year's trading holidays, verified against what was published ------------------

def pdf_text(pdf: bytes) -> str:
    """Text of a simple PDF (Flate streams, literal strings, WinAnsi): one line per text object. Enough for NSE
    circulars; a PDF using CID fonts returns little text and the caller must then not trust the parse."""
    import re
    import zlib

    def unescape(b: bytes) -> str:
        out, i = bytearray(), 0
        while i < len(b):
            c = b[i]
            if c == 0x5C and i + 1 < len(b):
                n = b[i + 1]
                i += 2
                if n in b"nrtbf":
                    out += {110: b"\n", 114: b"\r", 116: b"\t", 98: b"\b", 102: b"\f"}[n]
                elif 48 <= n <= 55:
                    j = k = i - 1
                    while k < len(b) and k < j + 3 and 48 <= b[k] <= 55:
                        k += 1
                    out.append(int(b[j:k], 8) & 255)
                    i = k
                else:
                    out.append(n)
            else:
                out.append(c)
                i += 1
        return out.decode("cp1252", "replace")

    lines = []
    for head, body in re.findall(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", pdf, flags=re.S):
        if b"FlateDecode" in head:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        for bt in re.findall(rb"BT(.*?)ET", body, flags=re.S):
            parts = []
            for arr in re.findall(rb"\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj", bt, flags=re.S):
                seg = arr[0] if arr[0] else b"(" + arr[1] + b")"
                for s, num in re.findall(rb"\(((?:\\.|[^\\)])*)\)|(-?\d+\.?\d*)", seg):
                    if s or not num:
                        parts.append(unescape(s))
                    elif float(num) < -200:
                        parts.append(" ")
            t = "".join(parts)
            if t.strip():
                lines.append(t)
    return "\n".join(lines)


DAYS = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"


def holidays_from_circular(text: str, year: int) -> dict:
    """Trading holidays from an NSE trading-holiday circular's text: the weekday table, the weekend table (split at
    'falling on Saturday / Sunday') and the Muhurat special session. Each row's day name must match its date."""
    import re
    flat = re.sub(r"\s+", " ", text)
    head, _, tail = flat.partition("falling on Saturday")
    row = re.compile(r"([A-Z][a-z]+ \d{1,2}, " + str(year) + r") (" + DAYS + r") ")

    def table(s):
        out = {}
        ms = list(row.finditer(s))
        for m, nxt in zip(ms, ms[1:] + [None]):
            d = datetime.strptime(m.group(1), "%B %d, %Y").date()
            if d.strftime("%A") != m.group(2):
                raise ValueError(f"circular day name disagrees with the date: {m.group(0)}")
            desc = s[m.end():nxt.start() if nxt else len(s)]
            desc = desc.split(" The holidays")[0].split(" National Stock")[0].split(" For and on")[0].strip()
            out[d] = re.sub(r" \d{1,2}$", "", desc).strip(" -")
        return out
    special = {datetime.strptime(m, "%B %d, %Y").date()
               for m in re.findall(r"Muhurat Trading will be conducted on \w+ ?, ([A-Z][a-z]+ \d{1,2}, \d{4})", flat)}
    return {"weekday_holidays": table(head), "weekend_holidays": table(tail), "special_sessions": special}


def calendar_year_from_circular(text: str, year: int, source_id: str):
    """CalendarYear built from a stored circular (no dates typed into code). A Muhurat day is a special session
    whose timetable is not loaded (blocked). Settlement holidays are not in a trading-holiday circular: they are set
    equal to the trading holidays and cited as an ASSUMPTION."""
    from .rules.calendar import CalendarYear
    from .rules.provenance import Cite, Status
    from .rules.types import Exchange
    h = holidays_from_circular(text, year)
    holidays = frozenset(d for d in h["weekday_holidays"] if d.weekday() < 5)
    if not holidays:
        raise ValueError("no holidays parsed from the circular")
    special = frozenset(d for d in h["special_sessions"] if d.year == year)
    cites = (Cite((source_id,), Status.PRIMARY, f"{len(holidays)} weekday trading holidays for {year}; special sessions "
                                                f"{sorted(x.isoformat() for x in special)} (timetable not loaded)."),
             Cite((source_id,), Status.ASSUMPTION, "Settlement holidays assumed equal to trading holidays (clearing "
                                                   "circular not held)."))
    return CalendarYear(Exchange.NSE, year, holidays - special, holidays - special, special, frozenset(), (), cites)


def research_calendar(market: Path, documents: Path, circulars: list[dict], base, base_report: dict) -> tuple:
    """(calendar, report) for a history folder: the base calendar's years, plus each stored circular (``documents``
    holds the gzipped PDF fetched from its official URL), plus observed publication for the rest of the stored
    window. A circular that is missing or does not parse is reported and its year stays observed."""
    import hashlib
    from datetime import date as _date
    from .rules.calendar import MarketCalendar
    from .rules.types import Exchange
    years = list(getattr(base, "_years", {}).values())
    have = {y.year for y in years if y.exchange is Exchange.NSE}
    report = dict(base_report, circulars={})
    for c in circulars:
        y, sid, url = int(c["year"]), c["source_id"], c["url"]
        if y in have:
            report["circulars"][str(y)] = {"source": sid, "result": "BASE_CALENDAR_HAS_YEAR"}
            continue
        pdf = read_document(documents, url)
        if pdf is None:
            report["circulars"][str(y)] = {"source": sid, "result": "DOCUMENT_NOT_STORED"}
            continue
        try:
            years.append(calendar_year_from_circular(pdf_text(pdf), y, sid))
            have.add(y)
            report["circulars"][str(y)] = {"source": sid, "url": url, "sha256": hashlib.sha256(pdf).hexdigest(), "result": "VERIFIED"}
        except ValueError as e:
            report["circulars"][str(y)] = {"source": sid, "result": "PARSE_FAILED", "error": str(e)}
    verified = MarketCalendar(tuple(years))
    recs = attempts(market).get("nse_bhavcopy", {})
    days = sorted(_date.fromisoformat(k) for k in recs)
    if not days:
        return verified, report
    observed = ObservedCalendar(market, days[0], days[-1])
    cal = CompositeCalendar(verified, observed)
    report.update(source="COMPOSITE", verified_years=sorted(have), observed_window=[days[0].isoformat(), days[-1].isoformat()],
                  cross_check=cal.cross_check())
    return cal, report


class CompositeCalendar:
    """Verified years (a MarketCalendar built from circulars or the holiday API) plus an ObservedCalendar for the
    rest. Inside a verified year, a weekend session that was published but is in no loaded circular (e.g. a Budget
    Saturday) is kept as a session and listed in ``observed_only``; such days do not count as verified."""

    def __init__(self, verified, observed: ObservedCalendar):
        from .rules.types import Exchange
        self.v, self.o, self._ex = verified, observed, Exchange.NSE
        self.observed_only = {d for d in observed.sessions if verified.covers(self._ex, d)
                              and not verified.is_trading_day(self._ex, d) and not verified.is_special_session(self._ex, d)}

    def basis_for(self, d):
        return "CALENDAR" if self.v.covers(self._ex, d) else ObservedCalendar.basis

    def covers(self, exchange, d):
        return self.v.covers(exchange, d) or self.o.covers(exchange, d)

    def is_trading_day(self, exchange, d):
        if self.v.covers(exchange, d):
            return d in self.observed_only or self.v.is_trading_day(exchange, d)
        return self.o.is_trading_day(exchange, d)

    def is_special_session(self, exchange, d):
        return self.v.is_special_session(exchange, d) if self.v.covers(exchange, d) else self.o.is_special_session(exchange, d)

    def session_open(self, exchange, d):
        if d in self.observed_only:
            return time(9, 0)
        return self.v.session_open(exchange, d) if self.v.covers(exchange, d) else self.o.session_open(exchange, d)

    def next_trading_day(self, exchange, d):
        n = d + timedelta(days=1)
        while not self.is_trading_day(exchange, n):
            n += timedelta(days=1)
        return n

    def previous_trading_day(self, exchange, d):
        p = d - timedelta(days=1)
        while not self.is_trading_day(exchange, p):
            p -= timedelta(days=1)
        return p

    def cross_check(self) -> dict:
        """Observed publication against the verified years, weekday by weekday over the observed window."""
        agree, cal_only, obs_only = 0, [], []
        d = self.o.start
        while d <= self.o.end:
            if self.v.covers(self._ex, d) and d.weekday() < 5:
                closed_v = not self.v.is_trading_day(self._ex, d)
                closed_o = d in self.o.closed
                if closed_v == closed_o and (closed_o or d in self.o.sessions):
                    agree += 1
                elif closed_v:
                    cal_only.append(d.isoformat())
                else:
                    obs_only.append(d.isoformat())
            d += timedelta(days=1)
        return {"weekdays_agreeing": agree, "closed_per_circular_but_published": cal_only,
                "published_closure_not_in_circular": obs_only,
                "observed_only_sessions": sorted(x.isoformat() for x in self.observed_only)}
