"""Regressions for the external audit of 2026-11-07 (tradebot-india-audit, run against commit 4555d368). Each test
reproduces one finding on synthetic data; none touches real runs."""
import json
from dataclasses import replace

from marketlab.quant import evaluate, ranking, registry


def _reports(tmp_path, *, dev_h=20, crit=None, dev_candidate="A"):
    runs = tmp_path / "runs"
    runs.mkdir()
    criteria = crit if crit is not None else {k: True for k in registry.REQUIRED_DEV_CRITERIA} | {"holdout_net_positive": None}
    dev = {"trial_id": "A.h20.x", "manifest_hash": "m", "policy_digest": "p", "holdout": False,
           "config": {"candidate": dev_candidate, "h": dev_h}, "promotion": {"criteria": criteria}}
    hold = {"trial_id": "A.h20.x", "manifest_hash": "m2", "policy_digest": "p", "holdout": True,
            "config": {"candidate": dev_candidate, "h": dev_h}, "net_rupees_total": 1.0}
    (runs / "dev.json").write_text(json.dumps(dev), encoding="utf-8")
    (runs / "hold.json").write_text(json.dumps(hold), encoding="utf-8")
    return runs


def test_a_complete_passing_report_still_promotes(tmp_path):
    runs = _reports(tmp_path)
    assert registry.write_promotion(runs, runs / "dev.json", runs / "hold.json", "A", 20) is not None
    rec, problems = registry.verified_promotion(runs, "A", 20, "p")
    assert rec is not None and problems == []


def test_an_incomplete_development_report_cannot_promote(tmp_path):
    for i, crit in enumerate(({"holdout_net_positive": None},  # the audit's counterexample
                              {k: True for k in registry.REQUIRED_DEV_CRITERIA[1:]})):  # one criterion missing
        folder = tmp_path / str(i)
        folder.mkdir()
        runs = _reports(folder, crit=crit)
        assert registry.write_promotion(runs, runs / "dev.json", runs / "hold.json", "A", 20) is None


def test_evidence_for_one_horizon_cannot_promote_another(tmp_path):
    runs = _reports(tmp_path, dev_h=20)
    assert registry.write_promotion(runs, runs / "dev.json", runs / "hold.json", "A", 60) is None  # the audit's case
    assert registry.verified_promotion(runs, "A", 60, "p")[0] is None


def test_required_criteria_match_what_the_evaluation_writes():
    out = evaluate.promotion({"config": {"h": 20}, "folds": []}, registry_reports=[], holdout_report=None)
    assert set(out["criteria"]) == set(registry.REQUIRED_DEV_CRITERIA) | {"holdout_net_positive"}
    assert out["verdict"] != "PROMOTED"  # no folds, no evidence


def test_every_result_changing_setting_changes_the_trial_id():
    base = evaluate.Config()
    for change in ({"seed": 123}, {"bootstrap": 1}, {"step_sessions": 60}, {"index_name": "Nifty 500"},
                   {"holdout_sessions": 200}):
        assert replace(base, **change).trial_id() != base.trial_id(), change
    assert replace(base, evaluate_holdout=True).trial_id() == base.trial_id()  # a holdout run is the same trial


def test_medians_of_even_counts_average_the_middle_pair():
    from datetime import date

    class V:
        def __init__(self, vals):
            self.vals = vals

        def cross_section(self, d):
            return [("I1", type("B", (), {"volume": 1, "value": self.vals[d.day - 1]})())]

    days = [date(2026, 1, d) for d in range(1, 5)]
    out = ranking._window_stats(V([10.0, 20.0, 30.0, 40.0]), days, days[-1], 4)
    assert out["I1"] == (4, 25.0)  # not 30.0, the upper-middle value


def test_a_zero_net_edge_sorts_by_its_value_not_last():
    cards = [{"gates": {"net_edge": -0.001}}, {"gates": {"net_edge": 0.0}}, {"gates": {"net_edge": None}},
             {"gates": {"net_edge": 0.002}}]
    order = [c["gates"]["net_edge"] for c in sorted(cards, key=ranking.edge_order)]
    assert order == [0.002, 0.0, -0.001, None]


def test_legacy_bhavcopy_maps_to_the_fields_the_panel_reads():
    import io
    import zipfile
    from marketlab.master import parse_legacy_bhavcopy
    csv_text = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
                "AAA,EQ,10,11,9.5,10.5,10.4,10,1000,10450.5,04-JAN-2016,12,INE000A01001,\n"
                ",EQ,1,1,1,1,1,1,1,1,04-JAN-2016,1,INE000A01002,\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm04JAN2016bhav.csv", csv_text)
    rows = parse_legacy_bhavcopy(buf.getvalue())
    assert len(rows) == 1  # a row without a symbol is dropped
    r = rows[0]
    assert (r["ISIN"], r["TckrSymb"], r["SctySrs"], r["FinInstrmTp"]) == ("INE000A01001", "AAA", "EQ", "STK")
    assert (r["OpnPric"], r["ClsPric"], r["PrvsClsgPric"], r["TtlTradgVol"], r["TtlTrfVal"], r["TtlNbOfTxsExctd"]) == \
        ("10", "10.5", "10", "1000", "10450.5", "12")


def test_calendar_reads_publication_in_either_bhavcopy_format(tmp_path, monkeypatch):
    from datetime import date
    from marketlab import history
    from marketlab.rules.types import Exchange
    fake = {"nse_bhavcopy_legacy": {"2020-02-01": {"result": "STORED"}, "2020-02-03": {"result": "STORED"},
                                    "2020-02-21": {"result": "NOT_PUBLISHED"}},
            "nse_bhavcopy": {"2024-07-08": {"result": "STORED"}}}
    monkeypatch.setattr(history, "attempts", lambda market: fake)
    cal = history.ObservedCalendar(tmp_path, date(2020, 1, 1), date(2024, 12, 31))
    assert cal.is_trading_day(Exchange.NSE, date(2020, 2, 1)) is True  # Budget Saturday seen in a legacy file
    assert cal.is_trading_day(Exchange.NSE, date(2020, 2, 21)) is False  # a holiday the legacy archive refused
    assert cal.is_trading_day(Exchange.NSE, date(2024, 7, 8)) is True
    assert cal.previous_trading_day(Exchange.NSE, date(2020, 2, 3)) == date(2020, 2, 1)
