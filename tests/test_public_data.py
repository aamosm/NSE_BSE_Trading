"""Public-file collector, point-in-time selection, security master and daily snapshot builder.

Fixtures copy the real header layouts observed on 5 Nov 2026 (docs/SOURCE_STATUS.md); values are synthetic.
"""
import io
import zipfile
from datetime import date, datetime

import pytest

from marketlab import master, sources
from marketlab.common import IST
from marketlab.rules.types import Framework, SurveillanceFlag

P, D = date(2026, 11, 4), date(2026, 11, 5)  # previous session, decision session
EVENING = datetime(2026, 11, 4, 20, 0, tzinfo=IST)
MONTH_END = date(2026, 10, 30)

UDIFF_HEAD = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
              "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
              "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")


def udiff(rows):
    body = UDIFF_HEAD + "".join(
        f"2026-11-04,2026-11-04,CM,NSE,STK,{code},{isin},{sym},{ser},,,,,{sym} LTD,1,1,1,{close},1,1,,{close},,,10,10,1,F1,1,,,,,\n"
        for code, isin, sym, ser, close in rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("BhavCopy_NSE_CM_0_0_0_20261104_F_0000.csv", body)
    return out.getvalue()


REG_HEAD = ("ScripCode,Symbol,Nse Exclusive,Status,Series,GSM,Long_Term_Additional_Surveillance_Measure (Long Term ASM),"
            "Unsolicited_SMS,Insolvency_Resolution_Process(IRP),Short_Term_Additional_Surveillance_Measure "
            "(Short Term ASM),Default,ICA,ESM\n")


def reg(sym, ser, status="A", gsm="100", lt="100", irp="100", st="100", ica="100", esm="100"):
    return f"NA,{sym},N,{status},{ser},{gsm},{lt},100,{irp},{st},100,{ica},{esm}\n"


FILES = {
    "EQUITY_L.csv": ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
                     "AAA,Aaa Limited,EQ,01-JAN-2010,10,1,INE000A00001,10\n"
                     "BBB,Bbb Limited,EQ,01-JAN-2012,10,1,INE000B00002,10\n"
                     "CCC,Ccc Limited,EQ,05-NOV-2026,10,1,INE000C00003,10\n").encode(),
    "sec_list_04112026.csv": ('Symbol,Series,Security Name,Band,Remarks\nAAA,EQ,AAA,No Band,"-"\nBBB,BE,BBB,5,"-"\n'
                              'CCC,EQ,CCC,20,"-"\nDDD,BE,DDD,2,"GSM STAGE - II"\nEEE,EQ,EEE,20,"-"\n').encode(),
    "REG1_IND041126.csv": (REG_HEAD + reg("AAA", "EQ") + reg("BBB", "BE", esm="1") + reg("CCC", "EQ")
                           + reg("DDD", "BE", gsm="2", status="S", ica="0") + reg("EEE", "BE")).encode(),
    "BhavCopy_NSE_CM_0_0_0_20261104_F_0000.csv.zip": udiff([
        ("1", "INE000A00001", "AAA", "EQ", "1128.20"), ("2", "INE000B00002", "BBB", "EQ", "60.56"),
        ("3", "INE000D00004", "DDD", "BE", "1.45"), ("5", "INE000E00005", "EEE", "EQ", "10.00")]),
    "BhavCopy_NSE_CM_0_0_0_20261030_F_0000.csv.zip": udiff([
        ("1", "INE000A00001", "AAA", "EQ", "1185.00"), ("2", "INE000B00002", "BBB", "EQ", "57.82")]),
    "fo_mktlots.csv": b"UNDERLYING                ,SYMBOL    ,NOV-26\nAAA LTD ,AAA       ,400\n",
    "Corporate_action.xml": b"""<?xml version="1.0"?><rss version="2.0"><channel><item>
        <title>Bbb Limited - Ex-Date: 05-Nov-2026</title><description>SERIES:EQ |PURPOSE:BONUS 1:1</description>
        <pubDate>04-Nov-2026 06:11:52</pubDate></item></channel></rss>""",
}


def fake_fetch(url):
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if name in FILES:
        return 200, FILES[name], "Wed, 04 Nov 2026 12:31:09 GMT"
    if "holiday" in name:
        raise TimeoutError
    return 404, b"", None


@pytest.fixture
def market(tmp_path):
    sources.collect(tmp_path, P, fetch=fake_fetch, pause=0, at=EVENING)
    sources.collect(tmp_path, MONTH_END, ["nse_bhavcopy"], fetch=fake_fetch, pause=0, at=EVENING)
    return tmp_path


def test_collector_stores_compressed_files_and_records_every_attempt(market):
    again = sources.collect(market, P, fetch=fake_fetch, pause=0, at=EVENING)
    by = {r["source"]: r["result"] for r in again}
    assert by["nse_bhavcopy"] == "ALREADY_STORED"
    assert by["bse_bhavcopy"] == "NOT_PUBLISHED" and by["nse_holidays"] == "FAILED"  # retried: not stored before
    assert sources.read_raw(market, "nse_sec_list", P).startswith(b"Symbol,Series")
    assert (market / "raw" / "nse_sec_list" / "2026-11-04.csv.gz").exists()
    rec = sources.stored(market, "nse_sec_list", P, datetime(2026, 11, 5, 9, tzinfo=IST))
    assert rec["payload"]["sha256"] and rec["payload"]["last_modified"].startswith("Wed")


def test_schema_change_is_flagged(tmp_path):
    def wrong(url):
        return 200, b"Unexpected,Columns\n1,2\n", None
    r = sources.collect(tmp_path, P, ["nse_sec_list"], fetch=wrong, pause=0, at=EVENING)
    assert r[0]["result"] == "SCHEMA_CHANGED"
    assert sources.stored(tmp_path, "nse_sec_list", P, datetime(2026, 11, 5, 9, tzinfo=IST)) is None


@pytest.mark.parametrize("url", ["http://nsearchives.nseindia.com/x.csv", "https://example.com/x.csv",
                                 "https://user@www.nseindia.com/x", "https://www.nseindia.com:8443/x"])
def test_fetch_is_limited_to_official_https_hosts(url):
    with pytest.raises(ValueError):
        sources.http_fetch(url)


def test_files_received_after_the_session_opens_are_not_used(tmp_path):
    late = datetime(2026, 11, 5, 9, 30, tzinfo=IST)
    sources.collect(tmp_path, P, fetch=fake_fetch, pause=0, at=late)
    snap, prov = master.build_nse_snapshot(tmp_path, "AAA", D)
    assert snap is None and prov["blocker"] == "NO_PREVIOUS_SESSION_BHAVCOPY"


def snap(market, symbol):
    return master.build_nse_snapshot(market, symbol, D)


def test_fno_stock_snapshot(market):
    s, prov = snap(market, "AAA")
    assert (s.isin, s.series, s.has_derivatives, s.price_band_pct) == ("INE000A00001", "EQ", True, None)
    assert str(s.base_price) == "1128.20" and str(s.tick_reference_price) == "1185.00"
    assert s.surveillance == frozenset() and s.suspended is False and s.in_periodic_call_auction is False
    assert s.mis_eligible is None and s.special_preopen_today is False and s.ltp is None
    assert set(prov["inputs"]) >= {"nse_bhavcopy", "nse_sec_list", "nse_reg_indicators", "nse_fo_mktlots"}


def test_series_change_surveillance_and_corporate_action(market):
    s, prov = snap(market, "BBB")  # EQ on 4 Nov, BE (ESM stage 1) for 5 Nov; bonus ex-date 5 Nov
    assert s.series == "BE" and "changed from EQ" in prov["fields"]["series"]
    assert s.surveillance == frozenset({SurveillanceFlag(Framework.ESM, 1)}) and str(s.price_band_pct) == "5"
    assert s.base_price is None and "ex-date today" in prov["fields"]["base_price"]


def test_suspension_call_auction_and_gsm_stage(market):
    s, _ = snap(market, "DDD")
    assert s.suspended is True and s.in_periodic_call_auction is True
    assert SurveillanceFlag(Framework.GSM, 2) in s.surveillance and s.has_derivatives is False


def test_listing_day_and_missing_inputs(market):
    s, prov = snap(market, "CCC")  # listed on D but not in the previous bhavcopy
    assert s is None and prov["blocker"] == "SYMBOL_NOT_UNIQUE_OR_NOT_TRADED_PREVIOUS_SESSION"


def test_conflicting_next_session_files_block(market):
    s, prov = snap(market, "EEE")  # sec_list says EQ, REG1_IND says BE
    assert s is None and prov["blocker"] == "SERIES_CONFLICT_BETWEEN_NEXT_SESSION_FILES"


def test_security_master_counts(market):
    out = master.build_master(market, D)
    assert out["nse"] == 3 and out["bse"] == 0 and out["isin_conflicts"] == 0
    assert out["nse_without_code"] == 1  # CCC lists on D; no previous-session code


def test_calendar_verification_against_nse_holiday_apis(tmp_path):
    import json as _json
    from marketlab.rules.calendar import NSE_2026
    trading = [{"tradingDate": d.strftime("%d-%b-%Y")} for d in sorted(NSE_2026.trading_holidays)]
    trading.append({"tradingDate": "01-Nov-2026"})  # a Sunday festival: ignored (weekday closures only)
    clearing = [{"tradingDate": d.strftime("%d-%b-%Y")} for d in sorted(NSE_2026.settlement_holidays)][:-1]

    def fetch(url):
        body = trading if "type=trading" in url else clearing
        return 200, _json.dumps({"CM": body}).encode(), None
    sources.collect(tmp_path, P, ["nse_holidays", "nse_clearing_holidays"], fetch=fetch, pause=0)
    out = sources.verify_nse_calendar(tmp_path, 2026)
    assert out["nse_holidays"]["state"] == "AGREES" and out["nse_holidays"]["api_weekdays"] == 16
    assert out["nse_clearing_holidays"]["state"] == "DIFFERS"
    assert out["nse_clearing_holidays"]["extra_in_engine"] == ["2026-12-25"]


def test_band_changes_are_fetched_for_the_session_they_take_effect_in(tmp_path):
    seen = []

    def fetch(url):
        seen.append(url.rsplit("/", 1)[-1])
        return 200, b"Sr. No,Symbol,Series,Security Name,From,To\n", None
    out = sources.collect(tmp_path, date(2026, 11, 6), ["nse_band_changes"], fetch=fetch, pause=0, at=EVENING)
    # Published after Friday 6 Nov; effective in the next session, the Sunday 8 Nov Muhurat session.
    assert seen == ["eq_band_changes_08112026.csv"] and out[0]["key"] == "2026-11-08"
