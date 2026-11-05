"""Security master and daily rules-input (InstrumentSnapshot) builder from stored official files.

Point-in-time rule: inputs for trading day D are only files whose first receipt precedes D's session
open. For a regular day that means the previous trading day's end-of-day files plus snapshot vintages
retrieved before the open. Every field reports its source file, receipt time and status (PRIMARY,
CROSS_CHECKED or ASSUMPTION); a field that cannot be established stays None, which the rules engine
treats as blocking. Identity is keyed by ISIN; listings on NSE and BSE are separate rows and are never
merged because an issuer name matches.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .common import IST, timestamp
from .rules.calendar import MarketCalendar
from .rules.types import Exchange, Framework, InstrumentSnapshot, RuleUnknown, SurveillanceFlag
from .sources import latest_vintage, read_raw, stored

REG_COLUMNS = {
    "GSM": Framework.GSM,
    "Long_Term_Additional_Surveillance_Measure (Long Term ASM)": Framework.LT_ASM,
    "Short_Term_Additional_Surveillance_Measure (Short Term ASM)": Framework.ST_ASM,
    "ESM": Framework.ESM,
    "Insolvency_Resolution_Process(IRP)": Framework.IBC,
    "Unsolicited_SMS": Framework.USM,
}
NOT_APPLICABLE = "100"
EQUITY_SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST", "SZ"})


def _rows(raw: bytes):
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _clean(row):
    return {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def parse_equity_list(raw: bytes):
    out = []
    for r in map(_clean, _rows(raw)):
        try:
            listed = datetime.strptime(r["DATE OF LISTING"], "%d-%b-%Y").date()
        except ValueError:
            listed = None
        out.append({"symbol": r["SYMBOL"], "series": r["SERIES"], "isin": r["ISIN NUMBER"],
                    "name": r["NAME OF COMPANY"], "listing_date": listed, "face_value": r["FACE VALUE"],
                    "market_lot": r["MARKET LOT"]})
    return out


def parse_bhavcopy(raw: bytes, zipped: bool):
    if zipped:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read(z.namelist()[0])
    return [_clean(r) for r in _rows(raw) if (r.get("FinInstrmTp") or "STK").strip() == "STK"]


def parse_sec_list(raw: bytes):
    out = {}
    for r in map(_clean, _rows(raw)):
        band = r["Band"]
        out[(r["Symbol"], r["Series"])] = {"band": None if band == "No Band" else band, "remarks": r["Remarks"]}
    return out


def parse_reg_indicators(raw: bytes):
    out = {}
    for r in map(_clean, _rows(raw)):
        flags, known = set(), True
        for col, framework in REG_COLUMNS.items():
            v = r.get(col, "")
            if v == NOT_APPLICABLE:
                continue
            if v.isdigit():
                flags.add(SurveillanceFlag(framework, int(v)))
            else:
                known = False
        status = {"A": False, "S": True}.get(r.get("Status", ""))
        ica = r.get("ICA", "")
        out[(r["Symbol"], r["Series"])] = {
            "surveillance": frozenset(flags) if known else None, "suspended": status,
            "call_auction": None if not ica else ica != NOT_APPLICABLE}
    return out


def parse_fo_underlyings(raw: bytes):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    return {r[1].strip() for r in rows[1:] if len(r) > 1 and r[1].strip() and r[1].strip() != "Symbol"}


def _num(x):
    try:
        d = Decimal(x)
    except (InvalidOperation, TypeError):
        return None
    return d if d.is_finite() and d > 0 else None


class Inputs:
    """Stored files usable for session D, chosen strictly by receipt time before D's open."""

    def __init__(self, market: Path, day: date, calendar: MarketCalendar | None = None, exchange=Exchange.NSE,
                 cutoff: datetime | None = None):
        self.market, self.day, self.cal = market, day, calendar or MarketCalendar()
        opens = self.cal.session_open(exchange, day)
        if opens is None:
            raise RuleUnknown(f"{day} is not a trading day")
        # Default: files first received before the session opens (pre-session decisions). A later decision
        # time may use files received before that time, never after it.
        self.cutoff = timestamp(cutoff) if cutoff else datetime.combine(day, opens, IST)
        self.previous = self.cal.previous_trading_day(exchange, day)
        self.used = {}

    def dated(self, spec_id, key=None):
        key = key or self.previous
        rec = stored(self.market, spec_id, key, self.cutoff)
        if rec is None:
            return None
        self.used[spec_id] = {"key": key.isoformat(), "sha256": rec["payload"]["sha256"],
                              "received_at": rec.get("received_at") or rec["available_at"],
                              "server_last_modified": rec["payload"].get("last_modified"),
                              "published_at": rec.get("published_at")}
        return read_raw(self.market, spec_id, key)

    def snapshot(self, spec_id):
        found = latest_vintage(self.market, spec_id, self.cutoff)
        if found is None:
            return None
        key, rec = found
        self.used[spec_id] = {"key": key.isoformat(), "sha256": rec["payload"]["sha256"],
                              "received_at": rec["available_at"]}
        return read_raw(self.market, spec_id, key)


def month_end_before(cal: MarketCalendar, exchange: Exchange, day: date) -> date:
    """Last trading day of the month before ``day``'s month (tick-size reference close date)."""
    d = day.replace(day=1)
    return cal.previous_trading_day(exchange, d)


def build_nse_snapshot(market: Path, symbol: str, day: date, calendar: MarketCalendar | None = None,
                       cutoff: datetime | None = None):
    """(InstrumentSnapshot | None, provenance). None when the security is not identifiable from stored files."""
    inp = Inputs(market, day, calendar, cutoff=cutoff)
    prov = {"day": day.isoformat(), "symbol": symbol, "cutoff": inp.cutoff.isoformat(),
            "previous_session": inp.previous.isoformat(), "fields": {}, "inputs": inp.used}
    f = prov["fields"]
    bhav_raw = inp.dated("nse_bhavcopy")
    if bhav_raw is None:
        prov["blocker"] = "NO_PREVIOUS_SESSION_BHAVCOPY"
        return None, prov
    rows = [r for r in parse_bhavcopy(bhav_raw, zipped=True) if r["TckrSymb"] == symbol and r["SctySrs"] in EQUITY_SERIES]
    if len(rows) != 1:
        prov["blocker"] = "SYMBOL_NOT_UNIQUE_OR_NOT_TRADED_PREVIOUS_SESSION"
        return None, prov
    row = rows[0]
    isin = row["ISIN"]
    f["isin"] = "PRIMARY: previous session bhavcopy"
    # After-close files (sec_list, REG1_IND) describe the NEXT session: on 4 Nov 2026 all three series
    # changes against that day's bhavcopy appeared identically in both files. Use them for D's series.
    band_raw, reg_raw = inp.dated("nse_sec_list"), inp.dated("nse_reg_indicators")
    bands_all = parse_sec_list(band_raw) if band_raw else {}
    reg_all = parse_reg_indicators(reg_raw) if reg_raw else {}
    band_series = {k[1] for k in bands_all if k[0] == symbol and k[1] in EQUITY_SERIES}
    reg_series = {k[1] for k in reg_all if k[0] == symbol and k[1] in EQUITY_SERIES}
    if band_series and reg_series and band_series != reg_series or len(band_series | reg_series) > 1:
        prov["blocker"] = "SERIES_CONFLICT_BETWEEN_NEXT_SESSION_FILES"
        return None, prov
    if band_series or reg_series:
        series = (band_series | reg_series).pop()
        f["series"] = ("CROSS_CHECKED: next-session series from sec_list and REG1_IND" if band_series and reg_series
                       else "PRIMARY: next-session series from one after-close file")
        if series != row["SctySrs"]:
            f["series"] += f" (changed from {row['SctySrs']} in the previous session)"
    else:
        series = row["SctySrs"]
        f["series"] = "ASSUMPTION: previous session series (no next-session file stored)"
    listing_raw = inp.snapshot("nse_equity_list")
    listed = [r for r in parse_equity_list(listing_raw) if r["isin"] == isin] if listing_raw else []
    name = listed[0]["name"] if len(listed) == 1 else None
    base = _num(row["ClsPric"])
    f["base_price"] = "PRIMARY: previous session close; ASSUMPTION: no corporate-action ex-date on D"
    ex_dates = corporate_action_ex_dates(inp, name) if name else None
    if ex_dates is None:
        f["base_price"] += " (corporate-action feed or company name not available)"
    elif day in ex_dates:
        base = None
        f["base_price"] = "UNKNOWN: corporate-action ex-date today; adjusted base price not loaded"
    fo_raw = inp.snapshot("nse_fo_mktlots")
    has_derivatives = (symbol in parse_fo_underlyings(fo_raw)) if fo_raw else None
    f["has_derivatives"] = "PRIMARY: F&O lot-size file vintage" if fo_raw else "UNKNOWN: F&O file not stored"
    band = bands_all.get((symbol, series))
    band_pct = _num(band["band"]) if band and band["band"] else None
    f["price_band_pct"] = ("PRIMARY: sec_list published after the previous session, describing D" if band
                           else "UNKNOWN: band file not stored or symbol absent")
    reg = reg_all.get((symbol, series))
    f["surveillance"] = ("CROSS_CHECKED: REG1_IND stage values (GSM matches sec_list remarks)" if reg
                         else "UNKNOWN: regulatory-indicator file not stored or symbol absent")
    f["suspended"] = "ASSUMPTION: REG1_IND Status S = suspended" if reg else "UNKNOWN"
    f["in_periodic_call_auction"] = "ASSUMPTION: REG1_IND ICA != 100 = call auction" if reg else "UNKNOWN"
    tick_ref = None
    try:
        ref_day = month_end_before(inp.cal, Exchange.NSE, day)
        ref_raw = inp.dated("nse_bhavcopy", ref_day) if ref_day != inp.previous else bhav_raw
        if ref_raw is not None:
            ref = [r for r in parse_bhavcopy(ref_raw, zipped=True) if r["ISIN"] == isin and r["SctySrs"] in EQUITY_SERIES]
            tick_ref = _num(ref[0]["ClsPric"]) if len(ref) == 1 else None
        f["tick_reference_price"] = (f"PRIMARY: close on {ref_day} (last trading day of previous month)"
                                     if tick_ref else f"UNKNOWN: {ref_day} bhavcopy not stored")
    except RuleUnknown as e:
        f["tick_reference_price"] = f"UNKNOWN: {e}"
    special = None
    if len(listed) == 1 and listed[0]["listing_date"]:
        special = listed[0]["listing_date"] == day
    f["special_preopen_today"] = ("ASSUMPTION: only a listing on D triggers the special pre-open (relistings not "
                                  "loaded)" if special is not None else "UNKNOWN: equity list not stored")
    f["mis_eligible"] = "UNKNOWN: broker intraday list not available"
    digest = hashlib.sha256(json.dumps([symbol, day.isoformat(), inp.used], sort_keys=True).encode()).hexdigest()
    snap = InstrumentSnapshot(
        as_of=day, exchange=Exchange.NSE, symbol=symbol, isin=isin, series=series, has_derivatives=has_derivatives,
        base_price=base, price_band_pct=band_pct, tick_size=None, tick_reference_price=tick_ref, ltp=None,
        surveillance=reg["surveillance"] if reg else None, in_periodic_call_auction=reg["call_auction"] if reg else None,
        suspended=reg["suspended"] if reg else None, special_preopen_today=special, mis_eligible=None,
        snapshot_id="NSE-" + digest[:16])
    prov["snapshot_id"] = snap.snapshot_id
    return snap, prov


def corporate_action_ex_dates(inp: Inputs, company_name: str):
    """Ex-dates for a company from the NSE corporate-action RSS vintage, or None when not stored.

    The feed names the company (not the symbol or ISIN), so the match is on the exact company name from
    the NSE equity list, case-insensitively. A renamed company would be missed: the result is evidence
    of an ex-date, never proof that none exists.
    """
    raw = inp.snapshot("nse_rss_corporate_actions")
    if raw is None:
        return None
    import xml.etree.ElementTree as ET
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return None
    dates, target = set(), company_name.strip().lower()
    for item in ET.fromstring(raw).findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if " - Ex-Date:" not in title:
            continue
        name, _, rest = title.partition(" - Ex-Date:")
        if name.strip().lower() != target:
            continue
        try:
            dates.add(datetime.strptime(rest.strip()[:11], "%d-%b-%Y").date())
        except ValueError:
            continue
    return dates


# ---- security master ---------------------------------------------------------------------------

def build_master(market: Path, day: date, calendar: MarketCalendar | None = None, cutoff=None) -> dict:
    """Listings usable for session ``day``: NSE (equity list + previous bhavcopy) and BSE (previous bhavcopy).

    Rows are (snapshot_date, exchange, isin, symbol, series) with exchange codes and the source of each.
    Rebuildable derived data; the raw files and catalog remain the evidence.
    """
    inp = Inputs(market, day, calendar, cutoff=cutoff)
    listings = []
    eq = inp.snapshot("nse_equity_list")
    nse_bhav = inp.dated("nse_bhavcopy")
    codes = {}
    if nse_bhav:
        for r in parse_bhavcopy(nse_bhav, zipped=True):
            codes[(r["TckrSymb"], r["SctySrs"])] = (r["FinInstrmId"], r["ISIN"])
    if eq:
        for r in parse_equity_list(eq):
            code = codes.get((r["symbol"], r["series"]))
            listings.append({"exchange": "NSE", "isin": r["isin"], "symbol": r["symbol"], "series": r["series"],
                             "exchange_code": code[0] if code else None, "name": r["name"],
                             "listing_date": r["listing_date"].isoformat() if r["listing_date"] else None,
                             "face_value": r["face_value"], "source": "nse_equity_list+nse_bhavcopy",
                             "isin_conflict": bool(code and code[1] != r["isin"])})
    bse_bhav = inp.dated("bse_bhavcopy")
    if bse_bhav:
        for r in parse_bhavcopy(bse_bhav, zipped=False):
            listings.append({"exchange": "BSE", "isin": r["ISIN"], "symbol": r["TckrSymb"], "series": r["SctySrs"],
                             "exchange_code": r["FinInstrmId"], "name": r.get("FinInstrmNm"), "listing_date": None,
                             "face_value": None, "source": "bse_bhavcopy (series = BSE group)", "isin_conflict": False})
    db = sqlite3.connect(market / "master.sqlite3")
    try:
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS listings (snapshot_date TEXT, exchange TEXT, isin TEXT,
                symbol TEXT, series TEXT, exchange_code TEXT, name TEXT, listing_date TEXT, face_value TEXT,
                source TEXT, isin_conflict INTEGER, PRIMARY KEY (snapshot_date, exchange, isin, symbol, series))""")
            db.execute("DELETE FROM listings WHERE snapshot_date=?", (day.isoformat(),))
            db.executemany("INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (day.isoformat(), x["exchange"], x["isin"], x["symbol"], x["series"], x["exchange_code"], x["name"],
                 x["listing_date"], x["face_value"], x["source"], int(x["isin_conflict"])) for x in listings])
    finally:
        db.close()
    isins = {x["isin"] for x in listings}
    both = {i for i in isins if {"NSE", "BSE"} <= {x["exchange"] for x in listings if x["isin"] == i}}
    return {"day": day.isoformat(), "inputs": inp.used, "listings": len(listings),
            "nse": sum(x["exchange"] == "NSE" for x in listings), "bse": sum(x["exchange"] == "BSE" for x in listings),
            "isins": len(isins), "isins_on_both": len(both), "isin_conflicts": sum(x["isin_conflict"] for x in listings),
            "nse_without_code": sum(x["exchange"] == "NSE" and not x["exchange_code"] for x in listings)}


def snapshot_json(s: InstrumentSnapshot | None) -> dict | None:
    if s is None:
        return None
    from dataclasses import fields
    out = {}
    for f in fields(s):
        v = getattr(s, f.name)
        if f.name == "surveillance" and v is not None:
            v = sorted(f"{x.framework}:{x.stage}" for x in v)
        elif v is not None and not isinstance(v, (bool, str, int)):
            v = str(v)
        out[f.name] = v
    return out
