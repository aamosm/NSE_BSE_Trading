"""Historical pilot plumbing: provenance, quarantine, observed sessions, format transition, immutable manifests,
evidence-gated rule files, filing units. Synthetic payloads; no network."""
import gzip
import io
import json
import zipfile
from datetime import date, datetime

import pytest

from marketlab import history, sources
from marketlab.common import IST
from marketlab.quant import pilot
from marketlab.quant.universe import rule_inputs_for
from marketlab.rules.types import RuleUnknown

UDIFF_HEAD = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,"
              "FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,"
              "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")
LEGACY_HEAD = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"


def zipped(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def udiff(day, rows):
    lines = [f"{day},{day},CM,NSE,STK,1,{i},{s},EQ,,,,,{s} LTD,{o},{h},{l},{c},{c},{p},,,,,{v},{val},5,F1,1,,,,," for i, s, o, h, l, c, p, v, val in rows]
    return zipped("x.csv", UDIFF_HEAD + "\n".join(lines) + "\n")


def legacy(day, rows):
    lines = [f"{s},EQ,{o},{h},{l},{c},{c},{p},{v},{val},{day},5,{i}," for i, s, o, h, l, c, p, v, val in rows]
    return zipped("cm.csv", LEGACY_HEAD + "\n".join(lines) + "\n")


ROWS = [("INE001A01001", "AAA", 10, 11, 9, 10.5, 10, 100, 1050.0), ("INE002A01001", "BBB", 20, 21, 19, 20.5, 20, 50, 1025.0)]
LM = "Thu, 17 Apr 2025 11:02:02 GMT"  # 16:32 IST the same day


def fake_fetch(table):
    def fetch(url):
        body, lm = table.get(url, (b"", None))
        return (200 if body else 404), body, lm
    return fetch


def test_a_schema_failure_is_quarantined_and_a_later_valid_file_repairs_it(tmp_path):
    spec = sources.BY_ID["nse_bhavcopy"]
    d = date(2025, 4, 17)
    url = sources.url_for(spec, d)
    bad = sources.collect(tmp_path, d, ["nse_bhavcopy"], fetch=fake_fetch({url: (zipped("x.csv", "WRONG,HEADER\n"), LM)}), pause=0)
    assert bad[0]["result"] == "SCHEMA_CHANGED" and "_quarantine" in bad[0]["path"]
    assert not sources.raw_path(tmp_path, spec, d).exists()  # the canonical path stays free
    good = sources.collect(tmp_path, d, ["nse_bhavcopy"], fetch=fake_fetch({url: (udiff("2025-04-17", ROWS), LM)}), pause=0)
    assert good[0]["result"] == "STORED" and sources.raw_path(tmp_path, spec, d).exists()
    rec = history.attempts(tmp_path)["nse_bhavcopy"]["2025-04-17"]
    av = history.availability("nse_bhavcopy", "2025-04-17", rec)
    assert av["availability_basis"] == "SERVER_LAST_MODIFIED" and av["reconstructed_available_at"].startswith("2025-04-17T16:32")
    assert av["received_at"] > "2026" and av["received_at"] != av["reconstructed_available_at"]  # receipt is never backdated


def test_a_server_time_far_after_the_file_date_is_not_availability_evidence():
    late = history.availability("x", "2025-04-17", {"last_modified": "Mon, 02 Jun 2025 10:00:00 GMT", "received_at": "2026-11-05"})
    assert late["availability_basis"] == "SERVER_TIME_OUTSIDE_EXPECTED_WINDOW" and late["reconstructed_available_at"] is None
    none = history.availability("x", "2025-04-17", {"received_at": "2026-11-05"})
    assert none["availability_basis"] == "NO_SERVER_TIME" and none["reconstructed_available_at"] is None


def test_observed_sessions_closures_and_unknowns(tmp_path):
    spec = sources.BY_ID["nse_bhavcopy"]
    table = {sources.url_for(spec, date(2025, 4, d)): (udiff(f"2025-04-{d:02d}", ROWS), LM) for d in (16, 17, 21)}
    for d in (16, 17, 18, 19, 21):  # 18 Apr: 404 (closure); 19 Apr Saturday: 404; 22 Apr: never attempted
        sources.collect(tmp_path, date(2025, 4, d), ["nse_bhavcopy"], fetch=fake_fetch(table), pause=0)
    cal = history.ObservedCalendar(tmp_path, date(2025, 4, 16), date(2025, 4, 22))
    assert cal.next_trading_day(None, date(2025, 4, 17)) == date(2025, 4, 21) and cal.is_trading_day(None, date(2025, 4, 18)) is False
    with pytest.raises(RuleUnknown):
        cal.is_trading_day(None, date(2025, 4, 22))
    r = cal.report()
    assert r["basis"] == "OBSERVED_PUBLICATION" and r["weekday_closures"] == ["2025-04-18"] and r["unknown_weekdays"] == ["2025-04-22"]


def test_the_format_transition_compares_the_same_session_field_by_field(tmp_path):
    d = date(2024, 7, 5)
    table = {sources.url_for(sources.BY_ID["nse_bhavcopy"], d): (udiff("2024-07-05", ROWS), LM),
             sources.url_for(sources.BY_ID["nse_bhavcopy_legacy"], d): (legacy("05-JUL-2024", ROWS[:1] + [ROWS[1][:5] + (20.6,) + ROWS[1][6:]]), LM)}
    assert sources.url_for(sources.BY_ID["nse_bhavcopy_legacy"], d).endswith("/2024/JUL/cm05JUL2024bhav.csv.zip")
    sources.collect(tmp_path, d, ["nse_bhavcopy", "nse_bhavcopy_legacy"], fetch=fake_fetch(table), pause=0)
    t = history.format_transition(tmp_path, d)
    assert t["comparable"] and t["joined"] == 2 and t["mismatches"]["ClsPric"] == 1 and t["mismatches"]["OpnPric"] == 0
    assert t["examples"][0]["isin"] == "INE002A01001" and "FinInstrmNm" in t["legacy_lacks"]


def test_manifests_are_written_once_and_detect_tampering(tmp_path):
    d = date(2025, 4, 17)
    sources.collect(tmp_path, d, ["nse_bhavcopy"], fetch=fake_fetch({sources.url_for(sources.BY_ID["nse_bhavcopy"], d): (udiff("2025-04-17", ROWS), LM)}), pause=0)
    man = history.build_manifest(tmp_path, "t", d, d, ids=("nse_bhavcopy",))
    history.write_once(tmp_path / "m.json", man)
    with pytest.raises(FileExistsError):
        history.write_once(tmp_path / "m.json", man)
    assert history.verify_manifest(tmp_path, man) == [] and man["missing"]["nse_bhavcopy"]["sessions_missing"] == 0
    p = sources.raw_path(tmp_path, sources.BY_ID["nse_bhavcopy"], d)
    p.write_bytes(gzip.compress(b"changed"))
    assert history.verify_manifest(tmp_path, man) == ["HASH_MISMATCH nse_bhavcopy 2025-04-17"]


def test_reconstructed_rule_files_need_server_evidence_before_the_open(tmp_path):
    cal = type("C", (), {"session_open": lambda s, e, d: __import__("datetime").time(9, 0), "covers": lambda s, e, d: True,
                         "is_trading_day": lambda s, e, d: d.weekday() < 5,
                         "previous_trading_day": lambda s, e, d: date(2025, 4, 17)})()
    sec = "Symbol,Series,Security Name,Band,Remarks\nINFY,EQ,Infosys,No Band,-\n"
    spec = sources.BY_ID["nse_sec_list"]
    url = sources.url_for(spec, date(2025, 4, 17))
    sources.collect(tmp_path, date(2025, 4, 17), ["nse_sec_list"], fetch=fake_fetch({url: (sec.encode(), "Thu, 17 Apr 2025 15:10:37 GMT")}), pause=0)
    ok = rule_inputs_for(tmp_path, date(2025, 4, 21), cal, "RECONSTRUCTED")
    assert ok["have_band"] and ok["evidence"]["nse_sec_list"]["admitted"] is True
    assert rule_inputs_for(tmp_path, date(2025, 4, 21), cal, "RECEIPT")["have_band"] is False  # received today, not before the open
    late = tmp_path / "late"
    sources.collect(late, date(2025, 4, 17), ["nse_sec_list"], fetch=fake_fetch({url: (sec.encode(), "Tue, 22 Apr 2025 05:00:00 GMT")}), pause=0)
    assert rule_inputs_for(late, date(2025, 4, 21), cal, "RECONSTRUCTED")["have_band"] is False  # published after the open


FILING = ("<table><tr><td>NSE Symbol</td><td>INFY</td></tr><tr><td>ISIN</td><td>INE009A01021</td></tr>"
          "<tr><td>Description of presentation currency</td><td>INR (in Actuals)</td></tr>"
          "<tr><td>Level of rounding used in financial results</td><td>Crores</td></tr>"
          "<tr><td>Financial Results Ind-AS</td></tr>"
          "<tr><td>D</td><td>Nature of report standalone or consolidated</td><td>Consolidated</td><td>Consolidated</td></tr>"
          "<tr><td>Revenue from operations</td><td>409250000000</td><td>1629900000000</td></tr>"
          "<tr><td>16</td><td>Total profit (loss) for period</td><td>70380000000</td><td>267500000000</td></tr></table>").encode()


def test_filing_fields_keep_unit_and_basis_and_catch_a_unit_mislabel():
    f = pilot.filing_fields(FILING)
    assert f["revenue_from_operations_inr"] == 409250000000 and f["revenue_from_operations_crore"] == 40925
    assert f["basis"] == "Consolidated" and f["net_profit_inr"] == 70380000000 and f["presentation_unit"] == "INR (in Actuals)"
    assert pilot.check_amount(f, 40925, "crore") is True and pilot.check_amount(f, 409250000000, "crore") is False
    assert pilot.classify_factor(0.5).startswith("SPLIT_OR_BONUS") and pilot.classify_factor(0.985).startswith("SMALL_DOWN")
