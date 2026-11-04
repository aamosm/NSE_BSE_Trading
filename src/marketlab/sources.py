"""Source register and polite collector for official public exchange files.

Every source lists its exact fields, acquisition route, publication/effective timing, rights status,
coverage and known missingness. Status values come from real retrievals (docs/SOURCE_STATUS.md);
nothing here guesses an endpoint or bypasses a control. A failed or refused retrieval is recorded as
evidence, not retried in a loop.

Bulk bytes are stored gzip-compressed under ``<market>/raw/<source>/<key>.<ext>.gz``; metadata (URL,
SHA-256, size, Last-Modified, receipt time, schema check) goes to ``<market>/catalog.sqlite3``, which
is separate from the private account evidence.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .common import now, timestamp
from .kite import NoRedirect, read_bounded
from .store import Store

ALLOWED_HOSTS = frozenset({"nsearchives.nseindia.com", "www.nseindia.com", "www.bseindia.com"})
USER_AGENT = "Mozilla/5.0 (MarketLab personal research; low-frequency daily files)"
MAX_FILE = 40 * 1024 * 1024
PAUSE_SECONDS = 1.5
RIGHTS_UNVERIFIED = ("UNVERIFIED: exchange website terms not reviewed in full. Assumed personal, non-redistributed "
                     "research use at one request per file per day. Do not publish or resell these files.")


@dataclass(frozen=True, slots=True)
class SourceSpec:
    id: str
    layer: str  # identity | rules | prices | events | calendar | account
    publisher: str
    url: str  # template: {yyyymmdd} {ddmmyyyy} {ddmmyy}; dated sources use the trading date
    ext: str
    dated: bool  # True: one file per trading date; False: current snapshot, keyed by retrieval date
    fields: tuple[str, ...]  # header columns that must be present (schema check)
    timing: str
    rights: str
    coverage: str
    missingness: str
    status: str  # WORKS | NOT_ATTEMPTED | BLOCKED  (as of the check date below)
    checked: date = date(2026, 11, 5)


REGISTER: tuple[SourceSpec, ...] = (
    SourceSpec("nse_equity_list", "identity", "NSE", "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
               "csv", False, ("SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "PAID UP VALUE", "MARKET LOT",
                              "ISIN NUMBER", "FACE VALUE"),
               "Current list only; no publication time in the file. Effective as of retrieval.",
               RIGHTS_UNVERIFIED, "All NSE mainboard equities currently available for trading (no history; "
               "delisted securities disappear). History exists only from our daily vintages.",
               "Exits and past series changes are missing unless captured by earlier vintages.", "WORKS"),
    SourceSpec("nse_sec_list", "rules", "NSE", "https://nsearchives.nseindia.com/content/equities/sec_list_{ddmmyyyy}.csv",
               "csv", True, ("Symbol", "Series", "Security Name", "Band", "Remarks"),
               "Published after the dated session closes (Last-Modified 18:01 IST observed for 3 Nov 2026). "
               "For session D the latest available file is the previous trading day's; treating it as D's "
               "bands is an ASSUMPTION until checked against band-change files.", RIGHTS_UNVERIFIED,
               "Every NSE equity series with a static band ('No Band' for F&O stocks) and a GSM remark.",
               "Not published on non-trading days (404).", "WORKS"),
    SourceSpec("nse_band_changes", "rules", "NSE",
               "https://nsearchives.nseindia.com/content/equities/eq_band_changes_{ddmmyyyy}.csv", "csv", True,
               ("Symbol", "Series", "From", "To"), "Published after close; effective date not stated in the file.",
               RIGHTS_UNVERIFIED, "Band revisions only.", "Not published on non-trading days.", "WORKS"),
    SourceSpec("nse_reg_indicators", "rules", "NSE", "https://nsearchives.nseindia.com/content/cm/REG1_IND{ddmmyy}.csv",
               "csv", True, ("Symbol", "Status", "Series", "GSM", "ESM", "ICA",
                             "Long_Term_Additional_Surveillance_Measure (Long Term ASM)",
                             "Short_Term_Additional_Surveillance_Measure (Short Term ASM)",
                             "Insolvency_Resolution_Process(IRP)", "Unsolicited_SMS"),
               "Published after close. Value 100 = measure not applicable, otherwise the stage (GSM column "
               "cross-checked against sec_list remarks for all overlapping rows). Status S = suspended and ICA = "
               "call auction are ASSUMPTIONS from column names; no NSE field definition found.",
               RIGHTS_UNVERIFIED, "3,224 NSE securities on 4 Nov 2026 (EQ, SM, BE, ST, BZ, SZ).",
               "Not published on non-trading days.", "WORKS"),
    SourceSpec("nse_bhavcopy", "prices", "NSE",
               "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip", "zip",
               True, ("TradDt", "FinInstrmTp", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "OpnPric", "HghPric",
                      "LwPric", "ClsPric", "LastPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal",
                      "TtlNbOfTxsExctd"),
               "End of day. Actual traded (unadjusted) prices; PrvsClsgPric on an ex-date is the adjusted base.",
               RIGHTS_UNVERIFIED, "All NSE CM instruments traded that day. UDiFF format.",
               "Untraded securities are absent; no bid/ask depth.", "WORKS"),
    SourceSpec("nse_bhavdata_full", "prices", "NSE",
               "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv", "csv", True,
               ("SYMBOL", "SERIES", "DATE1", "CLOSE_PRICE", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"),
               "End of day.", RIGHTS_UNVERIFIED, "Adds delivery quantity/percentage (liquidity evidence).",
               "No ISIN column; join through symbol and series on the same date.", "WORKS"),
    SourceSpec("nse_fo_mktlots", "rules", "NSE", "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", "csv",
               False, ("UNDERLYING", "SYMBOL"), "Current F&O lot sizes; membership as of retrieval.",
               RIGHTS_UNVERIFIED, "Underlyings with derivatives (decides CAS and dynamic bands).",
               "No history; additions/exits only through our vintages and NSE circulars.", "WORKS"),
    SourceSpec("nse_rss_corporate_actions", "events", "NSE",
               "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml", "xml", False, ("<rss",),
               "Rolling feed; item pubDate is the publication time.", RIGHTS_UNVERIFIED,
               "Recent and upcoming actions with ex-date, record date and purpose text.",
               "Rolling window only; amounts are free text; payment dates absent.", "WORKS"),
    SourceSpec("nse_rss_announcements", "events", "NSE",
               "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml", "xml", False, ("<rss",),
               "Rolling feed with publication times.", RIGHTS_UNVERIFIED, "Latest corporate announcements.",
               "Short rolling window: items are lost if not collected frequently.", "WORKS"),
    SourceSpec("nse_rss_financial_results", "events", "NSE",
               "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml", "xml", False, ("<rss",),
               "Rolling feed with publication times.", RIGHTS_UNVERIFIED, "Latest financial-result filings (links).",
               "Links only; figures need the filing itself.", "WORKS"),
    SourceSpec("nse_rss_board_meetings", "events", "NSE",
               "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml", "xml", False, ("<rss",),
               "Rolling feed.", RIGHTS_UNVERIFIED, "Upcoming board meetings (results dates).", "Rolling window.",
               "WORKS"),
    SourceSpec("nse_holidays", "calendar", "NSE", "https://www.nseindia.com/api/holiday-master?type=trading", "json",
               False, ('"CM"',), "Current year's trading holidays by segment.", RIGHTS_UNVERIFIED,
               "2026 only on 5 Nov 2026 (20 CM entries incl. weekend dates).",
               "Website API; may require a browser session in future (record failures, do not bypass).", "WORKS"),
    SourceSpec("bse_bhavcopy", "prices", "BSE",
               "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV", "csv",
               True, ("TradDt", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "ClsPric", "PrvsClsgPric", "TtlTradgVol"),
               "End of day. SctySrs carries the BSE group (fee group source).", RIGHTS_UNVERIFIED,
               "All BSE CM instruments traded that day.", "Untraded securities absent; BSE bands and surveillance "
               "lists not collected yet.", "WORKS"),
)
NOT_COLLECTED = (
    ("BSE holiday notice", "BLOCKED", "Direct retrieval refused in an earlier session; BSE calendar stays unloaded."),
    ("BSE scrip master / surveillance / bands", "NOT_ATTEMPTED", "api.bseindia.com requires browser headers; "
     "not attempted to avoid bypassing controls."),
    ("NSE corporate-actions and announcements API history", "NOT_ATTEMPTED",
     "www.nseindia.com/api/corporates-*: history beyond the RSS window not attempted yet."),
    ("NSE financial results (XBRL filings)", "NOT_ATTEMPTED", "Needed for company economics; next milestone."),
    ("Zerodha MIS eligibility list", "NOT_AVAILABLE", "No API; intraday paper sleeve stays blocked."),
    ("Historical bid/ask depth", "NOT_AVAILABLE", "Current depth cannot reconstruct the past; quotes are collected "
     "prospectively only."),
)
BY_ID = {s.id: s for s in REGISTER}


def url_for(spec: SourceSpec, day: date) -> str:
    return spec.url.format(yyyymmdd=day.strftime("%Y%m%d"), ddmmyyyy=day.strftime("%d%m%Y"), ddmmyy=day.strftime("%d%m%y"))


def raw_path(market: Path, spec: SourceSpec, key: date) -> Path:
    return market / "raw" / spec.id / f"{key.isoformat()}.{spec.ext}.gz"


def http_fetch(url: str, timeout=30):
    """GET an allowlisted exchange URL. Returns (status, body, last_modified). No cross-host redirects."""
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.username or u.port not in (None, 443):
        raise ValueError("Only allowlisted official exchange HTTPS hosts")
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as r:
            body = read_bounded(r, MAX_FILE, deadline=120)
            return r.status, body, r.headers.get("Last-Modified")
    except HTTPError as e:
        return e.code, b"", None


def schema_ok(spec: SourceSpec, body: bytes) -> bool:
    if spec.ext == "zip":
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                names = z.namelist()
                if len(names) != 1:
                    return False
                head = z.open(names[0]).read(4096)
        except zipfile.BadZipFile:
            return False
    else:
        head = body[:65536]
    text = head.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    probe = first if spec.ext in ("csv", "zip") else text
    cols = {c.strip() for c in first.split(",")} if spec.ext in ("csv", "zip") else set()
    return all((f in cols) if cols else (f in probe) for f in spec.fields)


def _write_gz(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(gzip.compress(body, mtime=0))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_raw(market: Path, spec_id: str, key: date) -> bytes | None:
    path = raw_path(market, BY_ID[spec_id], key)
    return gzip.decompress(path.read_bytes()) if path.exists() else None


def catalog(market: Path) -> Store:
    return Store(market / "catalog.sqlite3", max_bytes=512 * 1024 * 1024)


def collect(market: Path, day: date, ids=None, *, fetch=http_fetch, pause=PAUSE_SECONDS, at=None) -> list[dict]:
    """Fetch each selected WORKS source once for ``day`` (dated) or for today's vintage (snapshots).

    Idempotent: a stored file is not downloaded again. Every attempt, including 404 and failures, is
    recorded in the catalog with its receipt time.
    """
    results = []
    db = catalog(market)
    try:
        for spec in REGISTER:
            if (ids and spec.id not in ids) or spec.status != "WORKS":
                continue
            received = timestamp(at) if at else now()
            key = day if spec.dated else received.date()
            path = raw_path(market, spec, key)
            if path.exists():
                results.append({"source": spec.id, "key": key.isoformat(), "result": "ALREADY_STORED"})
                continue
            url = url_for(spec, day)
            try:
                status, body, modified = fetch(url)
            except (URLError, TimeoutError, OSError, ValueError) as e:
                status, body, modified, failure = None, b"", None, type(e).__name__
            else:
                failure = None
            published = None
            if modified:
                try:
                    published = parsedate_to_datetime(modified)
                except (TypeError, ValueError):
                    published = None
            record = {"url": url, "key": key.isoformat(), "http_status": status}
            if status == 200 and body:
                ok = schema_ok(spec, body)
                _write_gz(path, body)
                record.update(result="STORED" if ok else "SCHEMA_CHANGED", sha256=hashlib.sha256(body).hexdigest(),
                              bytes=len(body), path=path.relative_to(market).as_posix(), last_modified=modified)
            elif status == 404:
                record.update(result="NOT_PUBLISHED")
            else:
                record.update(result="FAILED", failure=failure or f"HTTP_{status}")
            db.append("source_file", "public:" + spec.id, key.isoformat(), record,
                      published_at=published if published and published <= received else None, received_at=received)
            results.append({"source": spec.id, **record})
            if pause:
                time.sleep(pause)
    finally:
        db.close()
    return results


def stored(market: Path, spec_id: str, key: date, before: datetime | None = None) -> dict | None:
    """Catalog record of a stored file whose first receipt is before ``before`` (point-in-time use)."""
    db = catalog(market)
    try:
        rows = db.as_of("source_file", key.isoformat(), before or now())
    finally:
        db.close()
    rows = [r for r in rows if r["payload"].get("result") == "STORED"
            and r["payload"].get("path", "").replace("\\", "/").startswith(f"raw/{spec_id}/")]
    return rows[-1] if rows else None


def latest_vintage(market: Path, spec_id: str, before: datetime, max_age_days=10) -> tuple[date, dict] | None:
    """Newest stored snapshot vintage (non-dated source) received before ``before``."""
    from datetime import timedelta
    d = timestamp(before).date()
    for _ in range(max_age_days + 1):
        rec = stored(market, spec_id, d, before)
        if rec:
            return d, rec
        d -= timedelta(days=1)
    return None
