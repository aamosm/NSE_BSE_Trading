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
        f = s["forecast"]
        # E19/E23: raw = common + specific; each part is shrunk by its own factor; the card states both
        assert f["mu_common"] + f["mu_specific"] == pytest.approx(f["mu_hat"], abs=1e-6)
        assert f["mu_shrunk"] == pytest.approx(f["shrink_common"] * f["mu_common"] + f["shrink_specific"] * f["mu_specific"],
                                               abs=2e-6)
        assert 0 <= f["shrink_specific"] <= 1 and 0 <= f["shrink_common"] <= 1
        if f["calibration_slope"] is not None:
            assert f["shrink_specific"] <= max(0.0, min(1.0, f["calibration_slope"])) + 1e-9  # E23 cap
        assert f["q10_abs"] <= f["q50_abs"] <= f["q90_abs"]  # E22 absolute range exists and is ordered
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


def test_restating_at_another_capital_changes_costs_and_classes_but_never_the_forecast(built):
    p, root, r = built
    base = {s["isin"]: s for s in r["stocks"]}
    seen = {}
    for w in (3_000.0, 10_000.0, 30_000.0):
        out = ranking.restate(r, w)
        assert out["policy"]["W"] == w and out["restated"]["basis"] == ranking.RESTATE_BASIS
        assert out.get("digest") is None and out.get("artifact") is None  # never a stored artifact
        assert sum(out["counts"].values()) == len(out["stocks"]) == len(r["stocks"])
        assert out["policy"]["K"] == allocate.Policy.for_capital(w).K
        for s in out["stocks"]:
            b = base[s["isin"]]
            if "forecast" in b and "forecast" in s:
                assert s["forecast"] == b["forecast"]  # the model is not refitted
                assert s["x"] == b["x"] and s["contributions"] == b["contributions"]
            if s.get("costs", {}).get("q"):
                cap = min(out["policy"]["cap_fraction"] * w, w * (1 - out["policy"]["reserve_fraction"]))
                assert s["costs"]["q"] == int(cap // s["close"])  # whole shares at this capital's cap
                assert s["costs"]["cost_fraction"] > 0
            assert s["class"] in ranking.CLASSES and s["reasons"]
            if s["class"] == "INELIGIBLE" and s["reasons"] == ["PRICE_ABOVE_HALF_POSITION"]:
                assert s["close"] > w * 0.5
        assert sum(1 for s in out["stocks"] if s["class"] == "BUY_CANDIDATE") <= out["policy"]["K"]
        seen[w] = {k: v for k, v in out["counts"].items()}
    # Bigger capital: cheaper round trip on the same stock, so the cost hurdle never rises.
    cf = lambda o, i: (next(s for s in o["stocks"] if s["isin"] == i).get("costs") or {}).get("cost_fraction")  # noqa: E731
    small, big = ranking.restate(r, 3_000.0), ranking.restate(r, 30_000.0)
    pairs = [(cf(small, i), cf(big, i)) for i in base if cf(small, i) and cf(big, i)]
    assert pairs and all(b <= s + 1e-12 for s, b in pairs)
    assert seen[3_000.0] != seen[30_000.0]  # the capital changes the calls


def test_restate_keeps_an_unranked_body_untouched():
    out = ranking.restate({"version": ranking.VERSION, "status": "NO_PANEL", "stocks": []}, 5_000.0)
    assert out["restated"]["basis"] == "NOT_RANKED" and out["stocks"] == []


def test_owner_screen_analyses_every_price_and_liquidity_and_labels_unaffordable(tmp_path):
    """E21: no price rule and no liquidity floor. A stock whose one share exceeds the per-stock cap keeps its forecast
    and is labelled ONE_SHARE_ABOVE_POSITION_CAP; no eligibility check refers to price or median value."""
    from marketlab import service
    p = make_panel(tmp_path / "p.sqlite3", n=420, n_stocks=30, bonus_at=10_000)
    root = tmp_path / "private"
    root.mkdir()
    W = 400.0  # a Rs 200 per-stock cap: synthetic prices run ~100-400, so the dearer half cannot be bought
    c = evaluate.Config(h=20, train_sessions=200, W=W, screen=service.screen_policy({"v_min_crore": 0.0}, W),
                        policy=allocate.Policy.for_capital(W))
    out = ranking.build(p, c, root=root, calendar=CAL, bootstrap=10, write=False)
    p.close()
    assert out["status"] == "RANKED" and out["screen_policy"]["price_max"] is None
    for s in out["stocks"]:
        assert {ch["rule"] for ch in s["checks"]}.isdisjoint({"PRICE_FITS_HALF_POSITION", "MEDIAN_VALUE_20"})
        assert s["class"] != "INELIGIBLE" or s["reasons"][0] not in ("PRICE_ABOVE_HALF_POSITION", "BELOW_V_MIN")
        if s.get("costs", {}).get("q") == 0 and "forecast" in s:
            assert s["costs"]["q_costed"] == 1 and s["costs"]["cost_fraction"] is not None  # costed at one share
            assert s["class"] in ("HOLD_OFF", "AVOID") and s["flip"] is not None
            if s["class"] == "HOLD_OFF":
                assert s["reasons"][0] == "ONE_SHARE_ABOVE_POSITION_CAP"
            explain.stock_view(s, out)  # the narrative renders for an unaffordable stock
    assert any(s.get("costs", {}).get("q") == 0 and "forecast" in s for s in out["stocks"])  # the case is exercised
    assert explain.day_summary(out) and explain.how_it_works(out)  # whole-ranking text renders too
    from marketlab import webapp
    assert all(webapp._stock_row(s)["class"] for s in out["stocks"])
    json.dumps(ranking.restate(out | {"digest": "x"}, 5_000.0), allow_nan=False)  # no Infinity reaches the browser


def test_restate_selects_among_passing_stocks_while_ineligible_cards_have_no_allocation(built):
    """Regression: the greedy selection must skip cards without an allocation block (ineligible, no forecast)."""
    import copy
    p, root, r = built
    body = copy.deepcopy(r)
    fc_cards = [s for s in body["stocks"] if "forecast" in s]
    strong = fc_cards[0]
    strong["forecast"].update(mu_shrunk=0.05, q10=-0.02)  # clears both gates at any capital
    body["stocks"].append({"isin": "INE000X01000", "symbol": "ZZZ", "class": "INELIGIBLE", "reasons": ["ETF"],
                           "close": 100.0, "checks": []})
    out = ranking.restate(body, 30_000.0)
    json.dumps(out, allow_nan=False)
    got = next(s for s in out["stocks"] if s["isin"] == strong["isin"])
    assert got["class"] == "BUY_CANDIDATE" and got["allocation"]["selected"]
    assert out["counts"]["BUY_CANDIDATE"] <= out["policy"]["K"]


def test_limits_are_owner_filters_that_move_calls_but_never_forecasts(built, tmp_path):
    from marketlab import service
    p, root, r = built
    strict = ranking.restate(r, 10_000.0, tail_limit=0.02)
    loose = ranking.restate(r, 10_000.0, tail_limit=0.50)
    assert strict["policy"]["tail_limit"] == 0.02 and loose["restated"]["tail_limit"] == 0.50
    by = lambda o: {s["isin"]: s for s in o["stocks"]}  # noqa: E731
    a, b = by(strict), by(loose)
    hr = lambda o: sum(1 for s in o["stocks"] if s["class"] == "HIGH_RISK")  # noqa: E731
    assert hr(loose) <= hr(strict)  # a looser loss limit can only move stocks out of high risk
    for isin, s in a.items():
        if "forecast" in s:
            assert s["forecast"] == b[isin]["forecast"]  # filters never touch the model
    higher_edge = ranking.restate(r, 10_000.0, min_edge=0.05)
    assert all(s["class"] not in ("BUY_CANDIDATE", "QUALIFIES") for s in higher_edge["stocks"]
               if "forecast" in s and s["forecast"]["mu_shrunk"] - (s["costs"]["cost_fraction"] or 0) < 0.05)
    pol = service.set_policy(tmp_path, {"min_edge": 0.002, "tail_limit": 0.12})
    eff = service.effective_policy(tmp_path, pol)
    assert (eff.min_edge, eff.tail_limit) == (0.002, 0.12) and eff.digest() != service.effective_policy(
        tmp_path, dict(pol, tail_limit=0.08)).digest()  # a changed limit is a different, recorded policy
    import pytest as _pt
    with _pt.raises(ValueError):
        service.set_policy(tmp_path, {"tail_limit": 5.0})


def test_a_forward_ranking_gets_one_frozen_outcome_file_with_every_prediction_beside_what_happened(tmp_path):
    """Stage 4: rank on 420 sessions before the next open; score against the same market 40 sessions later. Every
    scored card carries its prediction, the actual next-open entry and exit, the net after exact costs and where it
    fell against its ranges; the file is written once and never rewritten."""
    short = make_panel(tmp_path / "a.sqlite3", n=420, n_stocks=30, bonus_at=10_000)
    root = tmp_path / "private"
    root.mkdir()
    day = short.sessions()[-1]
    created = datetime(day.year, day.month, day.day, 20, 0, tzinfo=IST)  # the evening of the decision day
    r = ranking.build(short, cfg(), root=root, calendar=CAL, bootstrap=10, created_at=created)
    short.close()
    assert r["forward"]["eligible"] is True, r["forward"]
    long_ = make_panel(tmp_path / "b.sqlite3", n=460, n_stocks=30, bonus_at=10_000)
    assert long_.sessions()[:420] == [d for d in long_.sessions()[:420]] and long_.sessions()[419] == day
    rec = ranking.forward_record(long_, CAL, root)
    row = next(x for x in rec["rankings"] if x["day"] == r["day"])
    assert row["scored"] and row["pending"] == 0 and row["frozen"] and row["resolved"] > 0
    import json as _json
    from pathlib import Path as _P
    frozen = _json.loads(_P(row["frozen"]).read_text(encoding="utf-8"))
    resolved = [o for o in frozen["outcomes"] if o["status"] == "RESOLVED"]
    for o in resolved:
        assert abs(o["excess"] - (o["abs_log"] - o["index_log"])) < 2e-6  # excess = own return - index return
        if "net" in o:
            assert abs(o["net"] - (o["gross"] - o["actual_cost_fraction"])) < 2e-6 and o["would_fill"]
    before = _P(row["frozen"]).read_bytes()
    again = ranking.forward_record(long_, CAL, root)
    assert _P(row["frozen"]).read_bytes() == before  # never rewritten
    assert next(x for x in again["rankings"] if x["day"] == r["day"])["resolved"] == row["resolved"]
    long_.close()
