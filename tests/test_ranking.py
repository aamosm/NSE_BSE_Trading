"""Research ranking (RANK.v1): every stock classified with reasons and reproducible numbers; deterministic, write-once
artifacts; forward-evidence status; explanations that only format computed numbers."""
import json
import math
from datetime import datetime

import pytest

from marketlab import explain
from marketlab.common import IST
from marketlab.quant import allocate, evaluate, features, ranking
from marketlab.quant.universe import ScreenPolicy
from synthetic import WeekdayCalendar, make_panel

CAL = WeekdayCalendar()


def cfg(**kw):
    return evaluate.Config(h=20, train_sessions=200, screen=ScreenPolicy(v_min=1, W=10_000),
                           policy=allocate.Policy.for_capital(10_000), **kw)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rank")
    p = make_panel(tmp / "p.sqlite3", n=420, n_stocks=30, bonus_at=10_000)
    root = tmp / "private"
    root.mkdir()
    out = ranking.build(p, cfg(), root=root, calendar=CAL, bootstrap=10)
    yield p, root, out
    p.close()


def test_every_stock_has_a_class_and_reasons_with_numbers_that_add_up(built):
    p, root, r = built
    assert r["status"] == "RANKED" and r["version"] == ranking.VERSION
    assert sum(r["counts"].values()) == len(r["stocks"]) == len(p.cross_section(p.sessions()[-1]))
    for s in r["stocks"]:
        assert s["class"] in ranking.CLASSES and s["reasons"]
        if "forecast" not in s:
            continue
        con = s["contributions"]
        assert con["intercept"] + sum(i["contribution"] for i in con["items"]) == pytest.approx(s["forecast"]["mu_hat"], abs=1e-6)
        assert s["forecast"]["mu_shrunk"] == pytest.approx(s["forecast"]["mu_hat"] * s["forecast"]["shrink_factor"], abs=1e-6)
        c = s["costs"]
        assert c["value"] <= r["policy"]["cap_rupees"] and c["q"] == int(r["policy"]["cap_rupees"] // s["close"])
        assert s["gates"]["net_edge"] == pytest.approx(s["forecast"]["mu_shrunk"] - c["cost_fraction"], abs=1e-6)
        assert s["flip"]["edge_threshold"] == pytest.approx(c["cost_fraction"] + r["policy"]["min_edge"], abs=1e-6)
    ranks = sorted(s["rank"] for s in r["stocks"] if "rank" in s)
    assert ranks == list(range(1, len(ranks) + 1))


def test_classification_rules_in_order():
    pol = allocate.Policy.for_capital(10_000)

    def card(mu, q10, gates, selected=False):
        return {"gates": {"at_quantity": gates}, "forecast": {"mu_shrunk": mu, "q10": q10},
                "costs": {"cost_fraction": 0.01}, "allocation": {"selected": selected, "why_not": "NOT_SELECTED_K_LIMIT"}}
    assert ranking.classify(card(0.02, -0.03, [], True), pol)[0] == "BUY_CANDIDATE"
    assert ranking.classify(card(0.02, -0.03, []), pol) == ("QUALIFIES", ["NOT_SELECTED_K_LIMIT"])
    assert ranking.classify(card(-0.02, -0.03, ["EDGE_BELOW_COST_AT_QUANTITY"]), pol) == ("AVOID", ["MODEL_EXPECTS_UNDERPERFORMANCE"])
    cls, why = ranking.classify(card(0.005, -0.2, ["EDGE_BELOW_COST_AT_QUANTITY", "TAIL_LIMIT_AT_QUANTITY"]), pol)
    assert cls == "HIGH_RISK" and why[0] == "DOWNSIDE_TAIL_BEYOND_LIMIT"  # a risk call, not a negative view
    assert ranking.classify(card(-0.003, -0.03, ["EDGE_BELOW_COST_AT_QUANTITY"]), pol) == ("HOLD_OFF", ["EDGE_BELOW_COST", "LEANS_NEGATIVE"])
    # the avoid threshold mirrors the buy threshold: -(cost + minimum edge) = -1.1%
    assert ranking.classify(card(-0.011, -0.03, ["EDGE_BELOW_COST_AT_QUANTITY"]), pol)[0] == "AVOID"
    assert ranking.classify(card(-0.0109, -0.03, ["EDGE_BELOW_COST_AT_QUANTITY"]), pol)[0] == "HOLD_OFF"


def test_exchange_risk_flags_are_avoid_and_structural_exclusions_are_ineligible():
    assert ranking._risk_reason("UNDER_SURVEILLANCE") and ranking._risk_reason("BAND_5")
    assert not ranking._risk_reason("BELOW_V_MIN") and not ranking._risk_reason("PRICE_ABOVE_HALF_POSITION")


def test_the_artifact_is_deterministic_write_once_and_integrity_checked(built):
    p, root, r = built
    again = ranking.build(p, cfg(), root=root, calendar=CAL, bootstrap=10)
    assert again["digest"] == r["digest"] and again["created_at"] == r["created_at"]  # the first write wins
    assert len(ranking.list_rankings(root)) == 1 and ranking.load(root)["integrity"] == "OK"
    path = ranking.list_rankings(root)[0]["path"]
    body = json.loads(open(path, encoding="utf-8").read())
    body["stocks"][0]["class"] = "BUY_CANDIDATE" if body["stocks"][0]["class"] != "BUY_CANDIDATE" else "AVOID"
    body["day"] = "9999-12-31"  # an edited copy that would otherwise become the latest ranking
    folder = root.parent / "runs" / "rankings" / body["day"]
    folder.mkdir(parents=True)
    (folder / "edited.json").write_text(json.dumps(body), encoding="utf-8")
    assert ranking.load(root)["integrity"] == "DIGEST_MISMATCH"  # reported, not trusted
    (folder / "edited.json").unlink()
    folder.rmdir()
    assert ranking.load(root)["integrity"] == "OK"


def test_a_ranking_is_forward_evidence_only_before_the_entry_session_opens(built):
    p, root, r = built
    entry = datetime.fromisoformat(r["entry_session"])
    early = ranking._forward_status(CAL, entry.date(), datetime(entry.year, entry.month, entry.day, 8, 0, tzinfo=IST))
    late = ranking._forward_status(CAL, entry.date(), datetime(entry.year, entry.month, entry.day, 10, 0, tzinfo=IST))
    assert early["eligible"] is True and late == late | {"eligible": False, "why": "CREATED_AFTER_ENTRY_OPEN"}
    rec = ranking.forward_record(p, CAL, root)
    assert all(x["scored"] is False for x in rec["rankings"])  # this one was created long after its entry open


def test_explanations_only_format_the_computed_numbers(built):
    _, _, r = built
    for s in r["stocks"]:
        v = explain.stock_view(s, r)
        assert v["narrative"][0]["title"] == "The call" and v["class_info"]["title"]
        text = " ".join(x["text"] for x in v["narrative"]) + " ".join(i["text"] for i in v["insights"])
        assert "None" not in text and "nan%" not in text and "inf%" not in text  # no raw Python values leak through
        if "forecast" in s:
            assert explain.pct(s["forecast"]["mu_shrunk"]) in text  # the shrunk forecast is quoted, not recomputed
            assert any(i["code"] == "UNVALIDATED_MODEL" for i in v["insights"])
    how = explain.how_it_works(r)
    assert len(how["stages"]) == 15 and set(explain.FEATURE_INFO) == set(features.FEATURES)
    assert set(explain.CLASS_INFO) == set(ranking.CLASSES)


def test_every_reason_code_has_plain_text():
    codes = ["PASSES_GATES_AND_ALLOCATOR", "NOT_SELECTED_K_LIMIT", "NOT_IN_TOP_10_POOL", "NOT_SELECTED_PORTFOLIO_FIT",
             "EDGE_BELOW_COST", "LEANS_POSITIVE", "LEANS_NEGATIVE", "MODEL_EXPECTS_UNDERPERFORMANCE",
             "DOWNSIDE_TAIL_BEYOND_LIMIT", "FEATURES_MISSING", "NO_VOLATILITY_ESTIMATE", "SERIES_BE", "ETF",
             "NOT_TRADED_EVERY_SESSION", "BELOW_V_MIN", "PRICE_ABOVE_HALF_POSITION", "SUSPENDED", "PERIODIC_CALL_AUCTION",
             "SURVEILLANCE_UNKNOWN", "UNDER_SURVEILLANCE", "BAND_5", "MODEL_UNAVAILABLE:INSUFFICIENT_RESOLVED_LABELS"]
    for c in codes:
        t = explain.reason_text(c)
        assert t and t[0].isupper() and not t.startswith(c.split(":")[0].replace("_", " ").capitalize() + ".")


def test_feature_formatting_is_finite():
    assert explain.pct(None) == "unknown" and explain.pct(float("nan")) == "unknown" and explain.pct(0.0123) == "+1.23%"
    assert explain.crore(5e7) == "₹5.0 crore" and not math.isnan(float(explain.pct(0.5, sign=False).rstrip("%")))
