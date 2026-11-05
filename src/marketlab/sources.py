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
    # "session": the file is named after the session it was published after (most end-of-day files).
    # "next_session": the file is named after the session it takes effect in (published the evening before).
    url_date: str = "session"


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
               ("Symbol", "Series", "From", "To"),
               "Named after the session the changes take EFFECT in and published the evening before (file dated "
               "5 Nov 2026 had Last-Modified 4 Nov 18:00 IST; all 6 changes already appear in sec_list dated 4 Nov).",
               RIGHTS_UNVERIFIED, "Band revisions only.", "Not published on non-trading days.", "WORKS",
               url_date="next_session"),
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
    SourceSpec("nse_bhavcopy_legacy", "prices", "NSE",
               "https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{MON}/cm{dd}{MON}{yyyy}bhav.csv.zip",
               "zip", True, ("SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "LAST", "PREVCLOSE", "TOTTRDQTY",
                             "TOTTRDVAL", "TIMESTAMP", "TOTALTRADES", "ISIN"),
               "End of day (pre-UDiFF format). Last-Modified 5 Jul 2024 17:33 IST observed; the same day also has a "
               "UDiFF file (format overlap).", RIGHTS_UNVERIFIED,
               "NSE CM equities in the legacy CSV; no security name, instrument type or FinInstrmId columns.",
               "Not published on non-trading days; end date of publication not yet established.", "WORKS"),
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
    SourceSpec("nse_clearing_holidays", "calendar", "NSE", "https://www.nseindia.com/api/holiday-master?type=clearing",
               "json", False, ('"CM"',), "Current year's settlement (clearing) holidays by segment.", RIGHTS_UNVERIFIED,
               "2026 only on 5 Nov 2026 (20 CM dates).", "Website API; record failures, do not bypass.", "WORKS"),
    SourceSpec("nse_indices_close", "context", "NSE",
               "https://nsearchives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv", "csv", True,
               ("Index Name", "Index Date", "Open Index Value", "High Index Value", "Low Index Value",
                "Closing Index Value", "P/E", "P/B", "Div Yield"),
               "End of day; benchmark and sector index levels with P/E, P/B and dividend yield.", RIGHTS_UNVERIFIED,
               "All NSE indices that day (archive reaches at least 2 Jan 2020).", "Price indices only; total-return "
               "indices not in this file.", "WORKS"),
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
    return spec.url.format(yyyymmdd=day.strftime("%Y%m%d"), ddmmyyyy=day.strftime("%d%m%Y"), ddmmyy=day.strftime("%d%m%y"),
                           yyyy=day.strftime("%Y"), MON=day.strftime("%b").upper(), dd=day.strftime("%d"))


def quarantine_path(market: Path, spec: SourceSpec, key: date, sha: str) -> Path:
    return market / "raw" / spec.id / "_quarantine" / f"{key.isoformat()}.{sha[:12]}.{spec.ext}.gz"


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
            file_day = day
            if spec.dated and spec.url_date == "next_session":
                from .rules.calendar import MarketCalendar
                from .rules.types import Exchange, RuleUnknown
                try:
                    file_day = MarketCalendar().next_trading_day(Exchange.NSE, day)
                except RuleUnknown:
                    results.append({"source": spec.id, "key": day.isoformat(), "result": "FAILED",
                                    "failure": "CALENDAR_UNKNOWN_FOR_NEXT_SESSION"})
                    continue
            key = file_day if spec.dated else received.date()
            path = raw_path(market, spec, key)
            if path.exists():
                results.append({"source": spec.id, "key": key.isoformat(), "result": "ALREADY_STORED"})
                continue
            url = url_for(spec, file_day)
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
                sha = hashlib.sha256(body).hexdigest()
                # A payload that fails the schema check never takes the canonical path: it is quarantined, so a later
                # valid download for the same key is still fetched and promoted (review of 114589a).
                target = path if ok else quarantine_path(market, spec, key, sha)
                _write_gz(target, body)
                record.update(result="STORED" if ok else "SCHEMA_CHANGED", sha256=sha,
                              bytes=len(body), path=target.relative_to(market).as_posix(), last_modified=modified)
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


def verify_nse_calendar(market: Path, year: int, calendar=None) -> dict:
    """Compare the engine's NSE calendar with NSE's own holiday APIs (latest stored vintages).

    Weekend dates in the API list are ignored (the engine lists weekday closures only). Returns the
    differences; an empty difference on both lists is independent agreement, not proof of completeness.
    """
    import json as _json
    from .rules.calendar import MarketCalendar
    from .rules.types import Exchange
    cal = calendar or MarketCalendar()
    y = cal.year(Exchange.NSE, date(year, 1, 1))
    out = {}
    for spec_id, ours in (("nse_holidays", y.trading_holidays), ("nse_clearing_holidays", y.settlement_holidays)):
        found = latest_vintage(market, spec_id, now(), max_age_days=60)
        if not found:
            out[spec_id] = {"state": "NOT_STORED"}
            continue
        rows = _json.loads(read_raw(market, spec_id, found[0])).get("CM", [])
        api = {datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows}
        api_weekdays = {d for d in api if d.year == year and d.weekday() < 5}
        out[spec_id] = {"vintage": found[0].isoformat(), "api_dates": len(api), "api_weekdays": len(api_weekdays),
                        "missing_in_engine": sorted(d.isoformat() for d in api_weekdays - set(ours)),
                        "extra_in_engine": sorted(d.isoformat() for d in set(ours) - api_weekdays)}
        out[spec_id]["state"] = "AGREES" if not (out[spec_id]["missing_in_engine"] or out[spec_id]["extra_in_engine"])             else "DIFFERS"
    return out


def load_calendar(market: Path, fallback=None) -> tuple:
    """(MarketCalendar, report): years built from the latest stored NSE holiday-API vintages, with circular-sourced
    overrides; circular-based years are the fallback and the cross-check (differences are reported, API wins)."""
    import json as _json
    from .rules.calendar import DEFAULT_YEARS, MarketCalendar, compare_years, year_from_holiday_api
    from .rules.types import Exchange
    fallback = DEFAULT_YEARS if fallback is None else fallback
    report = {"source": "CIRCULAR", "years": sorted(y.year for y in fallback), "discrepancies": {}}
    t = latest_vintage(market, "nse_holidays", now(), max_age_days=400) if (market / "catalog.sqlite3").exists() else None
    c = latest_vintage(market, "nse_clearing_holidays", now(), max_age_days=400) if t else None
    if not t or not c:
        return MarketCalendar(fallback), report
    try:
        trading = _json.loads(read_raw(market, "nse_holidays", t[0])).get("CM", [])
        clearing = _json.loads(read_raw(market, "nse_clearing_holidays", c[0])).get("CM", [])
    except (ValueError, AttributeError):
        return MarketCalendar(fallback), report | {"error": "HOLIDAY_FILE_UNREADABLE"}
    years = sorted({int(str(e.get("tradingDate", ""))[-4:]) for e in trading if str(e.get("tradingDate", ""))[-4:].isdigit()})
    built = []
    for y in years:
        cy = year_from_holiday_api(Exchange.NSE, y, trading, clearing)
        circ = next((f for f in fallback if f.exchange is Exchange.NSE and f.year == y), None)
        if circ:
            diff = compare_years(circ, cy)
            if diff:
                report["discrepancies"][y] = diff
        built.append(cy)
    if not built:
        return MarketCalendar(fallback), report
    report.update(source="NSE_API", years=years, trading_vintage=t[0].isoformat(), clearing_vintage=c[0].isoformat())
    return MarketCalendar(tuple(built)), report


def load_calendar_for(market: Path) -> tuple:
    """``load_calendar``, extended for a history folder that declares ``calendar_sources.json``: every stored NSE
    holiday circular listed there becomes a verified year, and years with stored bhavcopies but no verified calendar
    are reconstructed from what the exchange published (history.ObservedCalendar, basis OBSERVED_PUBLICATION).
    Without the file this is exactly ``load_calendar``."""
    cal, report = load_calendar(market)
    spec_path = market / "calendar_sources.json"
    if not spec_path.exists():
        return cal, report
    import json as _json
    from . import history
    spec = _json.loads(spec_path.read_text(encoding="utf-8"))
    return history.research_calendar(market, (market / spec.get("documents", "../documents")).resolve(),
                                     spec.get("circulars", []), cal, report)
