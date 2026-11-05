"""NSE corporate-actions API import (verified against the manifest hashes), the expanded purpose parser on real
wording, deduplication, revised purposes, and features that apply a listed split/bonus instead of discarding a year
of history (including a split that moved the stock to a new ISIN)."""
import hashlib
import json
import math
import random
from datetime import date

import pytest

from marketlab import action_registry as ar
from marketlab.quant import evaluate, features
from marketlab.quant.panel import Panel
from marketlab.store import Store
from synthetic import WeekdayCalendar, index_csv, row, sessions

# verbatim subjects from NSE's corporate-actions API (2016-2025 responses, verification folder)
WORDING = {
    "Interim Dividend - Rs 5/- Per Share": [("DIVIDEND", 5.0)],
    "Dividend - Re 1/- Per Share": [("DIVIDEND", 1.0)],
    "Final Dividend Rs 6/- Plus Special Dividend Rs 4/- Per Share": [("DIVIDEND", 6.0), ("DIVIDEND", 4.0)],
    "Interim Dividend - Rs 2 Per Sh": [("DIVIDEND", 2.0)],
    "Annual General Meeting/Dividend - Rs 2.50 Per Share": [("DIVIDEND", 2.5), ("AGM", None)],
    "DIVIDEND-RS.10 PER SHARE (INCLUDING SPECIAL DIVIDEND OF RS.5/- PER SHARE).": [("DIVIDEND", 10.0)],
    "Fv Splt Frm Rs 10 To Rs 2": [("SPLIT", 0.2)],
    "Bonus- 1:2": [("BONUS", 2 / 3)],
    "Bonus Ncrps 1:10": [("BONUS_OTHER_SECURITY", None)],  # preference shares: no equity price factor
    "Annual General Meeting": [("AGM", None)],
    "Anual General Meeting": [("AGM", None)],  # NSE's own typo
    "Extra Ordinary General Meeting": [("EGM", None)],
    "Interim Dividend": [("DIVIDEND", None)],  # amount not stated: unknown, never guessed
    "Something Entirely New": [("UNPARSED", None)],
}


@pytest.mark.parametrize("subject, expected", WORDING.items())
def test_real_api_wording(subject, expected):
    got = ar.parse_purpose(subject)
    assert [(p["kind"], p.get("price_factor") or p.get("cash_per_share")) for p in got] == [
        (k, pytest.approx(v) if v else v) for k, v in expected]


def test_revised_purpose_marker_including_nse_typo():
    assert ar.is_revised("Interim Dividend Rs 8/- Per Share (Purpose Revised)")
    assert ar.is_revised("Interim Dividend-Rs 8/- Per Share (Purposed Revised)")
    assert not ar.is_revised("Interim Dividend Rs 8/- Per Share")


def _api_rows(ex):
    exs = ex.strftime("%d-%b-%Y")
    base = {"bcEndDate": "-", "bcStartDate": "-", "caBroadcastDate": None, "ind": "-", "ndEndDate": "-", "ndStartDate": "-",
            "recDate": exs, "series": "EQ", "exDate": exs, "faceVal": "10"}
    return [base | {"comp": "Alpha Limited", "isin": "INE00AA01001", "subject": "Bonus 1:1", "symbol": "AAA"},
            base | {"comp": "Beta Limited", "isin": "INE00BB01011", "subject": "Fv Splt Frm Rs 10 To Rs 5", "symbol": "BBB"},
            base | {"comp": "Gamma Limited", "isin": "INE00CC01001", "subject": "Interim Dividend - Rs 5/- Per Share", "symbol": "CCC"},
            base | {"comp": "Gamma Limited", "isin": "INE00CC01001", "subject": "Interim Dividend - Rs 5/- Per Share", "symbol": "CCC"},
            base | {"comp": "Gamma Limited", "isin": "INE00CC01001",
                    "subject": "Interim Dividend - Rs 6/- Per Share (Purpose Revised)", "symbol": "CCC"}]


def _panel(path, n=300, ex_t=280):
    """AAA: 1:1 bonus at session ex_t with NSE's unadjusted base (close/base ~ 0.5). BBB: 2:1 split onto a new ISIN.
    CCC: an ordinary stock with a dividend. Daily moves are small and random, so returns are ordinary elsewhere."""
    p = Panel(path)
    days = sessions(n, date(2023, 1, 2))
    rng = random.Random(3)
    a, b, c, lvl = 400.0, 300.0, 100.0, 10000.0
    for t, d in enumerate(days):
        ra, rb, rc = (rng.gauss(0, 0.01) for _ in range(3))
        pa, pb, pc = a, b, c
        if t == ex_t:
            a, b = a / 2, b / 2  # the action: share counts double, prices halve; NSE prints the old close as base
        a, b, c = a * math.exp(ra), b * math.exp(rb), c * math.exp(rc)
        rows = [row("INE00AA01001", "AAA", a, a * 1.01, a * 0.99, a, pa, 1e5, 1e8, name="ALPHA LIMITED"),
                row("INE00BB01011" if t < ex_t else "INE00BB01029", "BBB", b, b * 1.01, b * 0.99, b, pb, 1e5, 1e8, name="BETA LIMITED"),
                row("INE00CC01001", "CCC", c, c * 1.01, c * 0.99, c, pc, 1e5, 1e8, name="GAMMA LIMITED")]
        lvl *= math.exp(rng.gauss(0, 0.005))
        p.add_session(d, rows)
        p.add_index_file(d, index_csv(d, lvl))
    p.compute_implied_factors(WeekdayCalendar())
    p.compute_discontinuities(WeekdayCalendar())
    return p, days


def _folder(tmp_path, rows, *, tamper=False):
    folder = tmp_path / "ca"
    (folder / "raw").mkdir(parents=True)
    raw = json.dumps(rows).encode()
    (folder / "raw" / "2023.json").write_bytes(raw + (b" " if tamper else b""))
    (folder / "manifest.json").write_text(json.dumps({"source": "nse api", "files": [
        {"year": 2023, "url": "https://www.nseindia.com/api/corporates-corporateActions?index=equities", "received_at":
         "2026-11-05T12:00:00+00:00", "sha256": hashlib.sha256(raw).hexdigest()}]}), encoding="utf-8")
    return folder


def test_api_import_verifies_hashes_dedupes_and_keeps_every_field(tmp_path):
    p, days = _panel(tmp_path / "p.sqlite3")
    store = Store(tmp_path / "actions.sqlite3")
    bad = ar.import_verification_folder(store, _folder(tmp_path / "bad", _api_rows(days[280]), tamper=True))
    assert bad["files"][0]["result"] == "SHA256_MISMATCH" and bad["imported_rows"] == 0  # refused, not imported
    out = ar.import_verification_folder(store, _folder(tmp_path, _api_rows(days[280])))
    f = out["files"][0]
    assert f["result"] == "IMPORTED" and f["stored"] == 4 and f["duplicates_in_response"] == 1
    recs = ar.records(store)
    assert {r["api_isin"] for r in recs} == {"INE00AA01001", "INE00BB01011", "INE00CC01001"} and all(r["published_at"] is None for r in recs)
    assert all(r["source"] == ar.API_SOURCE and r["api_url"].startswith("https://www.nseindia.com/api/") for r in recs)
    idx = ar.ActionIndex(p, recs)
    store.close()
    ex = days[280]
    assert idx.factor("INE00AA01001", ex) == 0.5 and idx.return_factor("INE00AA01001", ex) == 0.5  # base not adjusted
    bbb = idx.get("INE00BB01011", ex)
    assert bbb.status == "RATIO_CONSISTENT" and bbb.successor_isin == "INE00BB01029"
    ccc = idx.get("INE00CC01001", ex)
    assert ccc.dividends == [("INTERIM", 6.0)] and ccc.dividend_cash == 6.0  # the revised amount supersedes, once
    rec = ar.reconcile(p, idx)
    assert rec["PRICE_DISCONTINUITY"].get("EXPLAINED_BY_LISTED_FACTOR") == 2 and rec["IDENTITY_END"] == {"EXPLAINED_BY_LISTED_FACTOR": 1}
    p.close()


def test_features_apply_listed_factors_and_follow_a_split_onto_its_new_isin(tmp_path):
    p, days = _panel(tmp_path / "p.sqlite3")
    store = Store(tmp_path / "actions.sqlite3")
    ar.import_verification_folder(store, _folder(tmp_path, _api_rows(days[280])))
    idx = ar.ActionIndex(p, ar.records(store))
    store.close()
    disc = p.discontinuities()
    d = days[290]
    # without the registry the bonus day is an unexplained jump: no feature row for a year after it
    plain = evaluate.security_history(p, "INE00AA01001", disc, None)
    assert d not in features.stock_feature_rows(plain["series"], plain["bad_days"])
    listed = evaluate.security_history(p, "INE00AA01001", disc, idx)
    rows = features.stock_feature_rows(listed["series"], listed["bad_days"], listed["return_factors"], listed["level_factors"])
    assert abs(rows[d]["ret_20"]) < 0.2 and 0 <= rows[d]["range_250"] <= 1  # an ordinary month, not -69%
    # the split moved BBB to a new ISIN: its history is joined to the old one because the action is listed
    new = evaluate.security_history(p, "INE00BB01029", disc, idx)
    assert new["lineage"] == ["INE00BB01011", "INE00BB01029"] and len(new["series"]["days"]) == len(days)
    rows_b = features.stock_feature_rows(new["series"], new["bad_days"], new["return_factors"], new["level_factors"])
    assert d in rows_b and abs(rows_b[d]["mom_12_1"]) < 1.0
    alone = evaluate.security_history(p, "INE00BB01029", disc, None)  # unexplained: never stitched
    assert alone["lineage"] == ["INE00BB01029"]
    p.close()


def test_features_are_unchanged_without_listed_actions(tmp_path):
    p, days = _panel(tmp_path / "p.sqlite3")
    s = p.series_arrays("INE00CC01001")
    a = features.stock_feature_rows(s, set())
    b = features.stock_feature_rows(s, set(), {}, {})
    assert a == b and len(a) == len(days) - features.MIN_HISTORY + 1
    p.close()
