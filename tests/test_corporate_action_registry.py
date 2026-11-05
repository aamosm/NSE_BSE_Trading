"""Listed corporate actions: parsing real NSE wording, official-record import, ISIN mapping, the ratio check
against observed prices, labels that apply a listed factor once and follow an ISIN successor, and the ledger."""
from datetime import date

import pytest

from marketlab import action_registry as ar
from marketlab.quant import labels, pilot
from marketlab.quant.panel import Panel
from marketlab.store import Store
from synthetic import WeekdayCalendar, index_csv, row, sessions

# verbatim purposes from NSE's Corporate_action.xml feed (stored 5 Nov 2026)
REAL = {"BONUS 1:1": [("BONUS", 0.5)],
        "FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RE 1/- PER SHARE": [("SPLIT", 0.1)],
        "INTERIM DIVIDEND - RS  5 PER SHARE": [("DIVIDEND", None)],
        "RIGHTS 3:8 @ PREMIUM RE 0.50/-": [("RIGHTS", None)],
        "BUY BACK": [("BUYBACK", None)]}

FEED = b"""<rss><channel>
<item><title>Concord Biotech Limited - Ex-Date: 13-Jan-2020 </title><link>x</link>
<description>SERIES:EQ |PURPOSE:BONUS 1:1 |FACE VALUE:1 |RECORD DATE:13-Jan-2020 |BOOK CLOSURE START DATE:- |BOOK CLOSURE END DATE:-</description>
<pubDate>09-Jan-2020 06:11:52</pubDate></item>
<item><title>Kaveri Seed Company Limited - Ex-Date: 13-Jan-2020 </title><link>x</link>
<description>SERIES:EQ |PURPOSE:INTERIM DIVIDEND - RS  5 PER SHARE |FACE VALUE:2 |RECORD DATE:13-Jan-2020</description>
<pubDate>09-Jan-2020 06:11:52</pubDate></item>
</channel></rss>"""


@pytest.mark.parametrize("purpose, expected", REAL.items())
def test_real_nse_purpose_wording_parses(purpose, expected):
    got = ar.parse_purpose(purpose)
    assert [(p["kind"], p.get("price_factor")) for p in got] == expected
    if expected[0][0] == "DIVIDEND":
        assert got[0]["cash_per_share"] == 5.0
    if expected[0][0] == "RIGHTS":
        assert (got[0]["ratio_new"], got[0]["ratio_held"], got[0]["premium"]) == (3, 8, 0.5)


def test_combined_and_unknown_purposes():
    two = ar.parse_purpose("FINAL DIVIDEND - RS 22 PER SHARE / SPECIAL DIVIDEND - RS 8 PER SHARE")
    assert [(p["label"], p["cash_per_share"]) for p in two] == [("FINAL", 22.0), ("SPECIAL", 8.0)]
    assert ar.parse_purpose("ANNUAL GENERAL MEETING")[0]["kind"] == "AGM"  # a non-price event, named as such
    assert ar.parse_purpose("SOMETHING NEW")[0]["kind"] == "UNPARSED"  # never guessed
    assert ar.parse_purpose("CONSOLIDATION OF SHARES FROM RE 1/- PER SHARE TO RS 10/- PER SHARE")[0]["price_factor"] == 10.0


def _panel(tmp_path):
    """Day 6 of 14: AAA 1:1 bonus with an unadjusted base; BBB 2:1 split onto a new ISIN; CCC listed 1:1 bonus that
    the prices do not show; Concord-like real numbers for DDD (base 1227.90, close 655.50)."""
    days = sessions(14, date(2020, 1, 1))
    p = Panel(tmp_path / "p.sqlite3")
    for t, d in enumerate(days):
        a_pc, a_c = (400.0, 200.0) if t == 6 else ((400.0, 400.0) if t < 6 else (200.0, 200.0))
        rows = [row("INE00AA01001", "AAA", a_c, a_c * 1.01, a_c * 0.99, a_c, a_pc, 1e5, 1e8, name="AAA LIMITED")]
        if t < 6:
            rows.append(row("INE00BB01011", "BBB", 300.0, 303.0, 297.0, 300.0, 300.0, 1e5, 1e8, name="BBB LTD"))
        else:
            rows.append(row("INE00BB01029", "BBB", 150.0, 151.5, 148.5, 150.0, 300.0 if t == 6 else 150.0, 1e5, 1e8, name="BBB LTD"))
        rows.append(row("INE00CC01001", "CCC", 100.0, 101.0, 99.0, 100.0, 100.0, 1e5, 1e8, name="CCC LIMITED"))
        d_pc, d_c = (1227.9, 655.5) if t == 6 else ((1227.9, 1227.9) if t < 6 else (655.5, 655.5))
        rows.append(row("INE338H01029", "CONCORDBIO", d_c, d_c * 1.01, d_c * 0.99, d_c, d_pc, 1e5, 1e8, name="CONCORD BIOTECH LIMITED"))
        p.add_session(d, rows)
        p.add_index_file(d, index_csv(d, 10000.0))
    p.compute_implied_factors(WeekdayCalendar())
    p.compute_discontinuities(WeekdayCalendar())
    return p, days


def _index(tmp_path, p, days, extra_csv=""):
    store = Store(tmp_path / "actions.sqlite3")
    ar.ingest_rss(store, FEED.replace(b"13-Jan-2020", days[6].strftime("%d-%b-%Y").encode()), sha256="f" * 64,
                  received_at="2026-11-05T10:00:00+05:30")
    csv_path = tmp_path / "CF-CA.csv"
    ex = days[6].strftime("%d-%b-%Y")
    csv_path.write_text('"SYMBOL","COMPANY NAME","SERIES","PURPOSE","FACE VALUE","EX-DATE","RECORD DATE"\n'
                        f'"AAA","AAA Limited","EQ","BONUS 1:1","10","{ex}","{ex}"\n'
                        f'"BBB","BBB Limited","EQ","FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 5/- PER SHARE","10","{ex}","{ex}"\n'
                        f'"CCC","CCC Limited","EQ","BONUS 1:1","10","{ex}","{ex}"\n'
                        '"BAD","x","EQ","BONUS 1:1","10","not a date",""\n' + extra_csv, encoding="utf-8")
    imp = ar.import_nse_csv(store, csv_path, received_at="2026-11-05T10:00:00+05:30")
    idx = ar.ActionIndex(p, ar.records(store))
    store.close()
    return idx, imp


def test_records_are_mapped_and_every_ratio_is_checked_against_the_prices(tmp_path):
    p, days = _panel(tmp_path)
    idx, imp = _index(tmp_path, p, days)
    assert imp["stored"] == 3 and imp["skipped"] == 1
    ex = days[6]
    assert idx.get("INE00AA01001", ex).status == "RATIO_CONSISTENT" and idx.factor("INE00AA01001", ex) == 0.5
    bbb = idx.get("INE00BB01011", ex)
    assert bbb.status == "RATIO_CONSISTENT" and bbb.successor_isin == "INE00BB01029"  # the split moved the ISIN
    ccc = idx.get("INE00CC01001", ex)
    assert ccc.status == "RATIO_INCONSISTENT" and idx.factor("INE00CC01001", ex) is None  # listed, but prices disagree
    concord = idx.get("INE338H01029", ex)  # mapped from the feed by the company name printed in the bhavcopy
    assert concord.status == "RATIO_CONSISTENT" and concord.observed_ratio / 0.5 == pytest.approx(1.0677, abs=1e-4)
    assert [r["company"] for r in idx.unmapped] == ["Kaveri Seed Company Limited"]  # not in this panel: reported
    assert idx.unmapped[0]["why"] == "NO_ISIN_MATCH"
    p.close()


def test_labels_apply_a_listed_factor_once_and_follow_the_successor_isin(tmp_path):
    p, days = _panel(tmp_path)
    idx, _ = _index(tmp_path, p, days)
    a = labels.forward_return(p, "INE00AA01001", days[3], 5, sessions=days, actions=idx)
    assert a.status == labels.RESOLVED and a.factor == 0.5 and a.gross == pytest.approx(0.0) and a.basis == "RECONSTRUCTED_LISTED"
    b = labels.forward_return(p, "INE00BB01011", days[3], 5, sessions=days, actions=idx)
    assert b.status == labels.RESOLVED and b.exit_open == 150.0 and b.gross == pytest.approx(0.0)  # successor's exit
    c = labels.forward_return(p, "INE00CC01001", days[3], 5, sessions=days, actions=idx)
    assert c.status == labels.RESOLVED and c.factor == 1.0  # an inconsistent listing changes nothing: no jump, no factor
    without = labels.forward_return(p, "INE00AA01001", days[3], 5, sessions=days)
    assert without.reason == "PRICE_DISCONTINUITY_UNEXPLAINED"  # unchanged behaviour without the registry
    p.close()


def test_the_ledger_restates_units_and_moves_the_holding_to_the_successor(tmp_path):
    p, days = _panel(tmp_path)
    idx, _ = _index(tmp_path, p, days)
    tr = pilot.mechanical_trace(p, days, set(days), "INE00BB01011", days[2], 10, 6, median_value=1e8, actions=idx)
    (t,) = tr["trades"]
    assert t["isin"] == "INE00BB01029" and t["units_exit"] == 20.0 and t["action_status"] == "FACTOR_LISTED"
    assert t["gross_rupees_at_open"] == pytest.approx(0.0) and [e["event"] for e in tr["events"]].count("ISIN_SUCCESSION") == 1
    p.close()


def test_a_bad_csv_header_is_refused(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("A,B,C\n1,2,3\n", encoding="utf-8")
    store = Store(tmp_path / "a.sqlite3")
    with pytest.raises(ValueError, match="unrecognised header"):
        ar.import_nse_csv(store, bad, received_at="2026-11-05T10:00:00+05:30")
    store.close()
