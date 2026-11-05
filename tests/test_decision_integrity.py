"""Checkpoint A: dashboard and decision integrity (review of 114589a). Synthetic fixtures; no network, no account."""
import json
import sys
from datetime import date, datetime, timedelta

import pytest

from marketlab import cli, decisions, service, webapp
from marketlab.common import IST, atomic_json
from marketlab.quant import allocate, candidates, decide, evaluate, registry
from marketlab.quant.allocate import Candidate, Policy
from marketlab.quant.panel import Panel
from marketlab.quant.universe import ScreenPolicy
from marketlab.rules import MarketCalendar
from synthetic import make_panel

CAL = MarketCalendar()


def at(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=IST)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "private"
    r.mkdir()
    return r


def cfg(**kw):
    base = dict(h=20, train_sessions=400, test_sessions=60, step_sessions=60, holdout_sessions=120, bootstrap=0,
                screen=ScreenPolicy(v_min=1, W=10_000))
    base.update(kw)
    return evaluate.Config(**base)


# ---- every attempt is durable, one id in both views ---------------------------------------------------------

def test_every_early_wait_is_recorded_and_both_views_show_the_same_id(root, tmp_path):
    no_panel = decide.run(None, cfg(), root=root, origin="cli")
    assert no_panel["action"] == "WAIT" and no_panel["reasons"] == ["MODEL_NOT_PROMOTED", "PANEL_NOT_BUILT"]
    short = make_panel(tmp_path / "short.sqlite3", n=30)
    try:
        early = decide.run(short, cfg(), root=root, origin="cli")
    finally:
        short.close()
    assert early["reasons"] == ["MODEL_NOT_PROMOTED", "INSUFFICIENT_HISTORY"]
    for e in (no_panel, early):
        assert (tmp_path / "runs" / e["artifact"]).exists() and e["decision_id"].startswith(e["day"].replace("-", ""))
    line = decisions.timeline(root)
    assert [x["decision_id"] for x in line] == [early["decision_id"], no_panel["decision_id"]]
    st = webapp.status(root, tmp_path / "market", at(5, 10), calendar=CAL)
    assert st["latest_decision"]["decision_id"] == st["decisions"][0]["decision_id"] == early["decision_id"]
    view = webapp.decision_view(root)
    assert view["decision"]["decision_id"] == early["decision_id"] and view["decision"]["integrity"] == "OK"
    assert webapp.decision_view(root, no_panel["decision_id"])["decision"]["reasons"][-1] == "PANEL_NOT_BUILT"


def test_controls_request_records_through_the_same_recorder(root, tmp_path):
    req = service.submit_request(root, "decide")
    ctx = service.Context(root, tmp_path / "market", [], calendar=CAL)
    service.process_requests(ctx, at(5, 10))
    ctx._request_thread.join(20)
    done = service.list_requests(root)[0]
    assert done["state"] == "DONE" and done["result"]["action"] == "WAIT" and done["id"] == req["id"]
    rec = decisions.load(root, done["result"]["decision_id"])
    assert rec["origin"] == "controls" and rec["request_id"] == req["id"] and "PANEL_NOT_BUILT" in rec["reasons"]
    assert decisions.timeline(root)[0]["decision_id"] == done["result"]["decision_id"]


def test_a_reused_decision_id_never_overwrites_the_first_record(root):
    a = decisions.record(root, {"day": "2026-11-05", "action": "WAIT", "reasons": ["X"]}, origin="scheduler", decision_id="d1")
    b = decisions.record(root, {"day": "2026-11-05", "action": "WAIT", "reasons": ["Y"]}, origin="scheduler", decision_id="d1")
    assert a == b and decisions.load(root, "d1")["reasons"] == ["X"]
    with pytest.raises(ValueError):
        decisions.record(root, {"day": "2026-11-05", "action": "PAPER_PLAN", "reasons": []}, origin="cli")  # no promotion


# ---- candidates dispatch to builders that exist ------------------------------------------------------------

def test_unimplemented_candidates_and_unregistered_trials_are_refused(root, tmp_path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="UNIMPLEMENTED"):
        service.set_policy(root, {"candidate": "B"})
    with pytest.raises(ValueError, match="UNIMPLEMENTED"):
        service.set_policy(root, {"families": {"C": True}})
    with pytest.raises(ValueError, match="UNREGISTERED_HORIZON"):
        service.set_policy(root, {"h": 30})
    with pytest.raises(ValueError, match="UNIMPLEMENTED"):
        service.submit_request(root, "evaluate", {"candidate": "B", "h": 20})
    with pytest.raises(candidates.Unimplemented, match="UNREGISTERED_ABLATION"):
        candidates.require("A", 20, ("vol_20",))
    rec = decide.run(None, cfg(candidate="B"), root=root, origin="cli")
    assert rec["reasons"] == ["UNIMPLEMENTED_CANDIDATE"] and "family B" in rec["record"]["detail"]
    pn = make_panel(tmp_path / "p.sqlite3", n=40)
    try:
        with pytest.raises(candidates.Unimplemented):
            evaluate.walk_forward(pn, cfg(candidate="C"), runs=tmp_path / "runs", calendar=CAL, progress=lambda *_: None)
    finally:
        pn.close()
    monkeypatch.setattr(sys, "argv", ["marketlab", "--private-dir", str(root), "--market-dir", str(tmp_path / "m"),
                                      "evaluate", "--candidate", "B", "--h", "20"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2 and "UNIMPLEMENTED" in capsys.readouterr().err


def test_reports_name_the_builder_columns_and_event_records():
    d = candidates.describe(candidates.require("A", 20, ("mom_12_1",)), ("mom_12_1",))
    assert d["feature_builder"] == "features.set_a.v1" and "mom_12_1" not in d["feature_columns"]
    assert d["ablated_columns"] == ["mom_12_1"] and d["event_records_used"] == 0


# ---- the effective policy reaches the allocator and every record --------------------------------------------

def test_a_25_percent_cap_binds_every_position_and_is_persisted(root):
    service.set_policy(root, {"cap_fraction": 0.25})
    eff = service.effective_policy(root)
    assert eff.cap_fraction == 0.25 and eff.to_json()["cap_rupees"] == 2500.0 and eff.K == 2  # K from the spec tier
    strong = [Candidate("INE000A01001", 120.0, 0.03, 0.05), Candidate("INE001A01001", 90.0, 0.028, 0.05)]
    corr = [[1.0, 0.3], [0.3, 1.0]]
    plan = allocate.plan(strong, corr, eff, eff.W * (1 - eff.reserve_fraction))
    assert plan["quantities"] and all(v <= 2500.0 for v in plan["values"].values())
    wide = allocate.plan(strong, corr, Policy.for_capital(10_000), 8_000)
    assert max(wide["values"].values()) > 2500.0  # the default 50% cap would have allowed more
    rec = service.scheduled_decision(service.Context(root, root.parent / "market", [], calendar=CAL), date(2026, 11, 5))
    full = decisions.load(root, rec["decision_id"])
    assert full["policy"]["cap_rupees"] == 2500.0 and full["policy_digest"] == eff.digest()
    gamma = service.set_policy(root, {"risk_multiplier": 0.5}) and service.effective_policy(root).risk_aversion()
    assert gamma == pytest.approx(2 / (0.5 * 10_000))


def test_evaluation_trial_identity_includes_the_policy():
    a = cfg(policy=Policy.from_owner({"capital": 10_000, "cap_fraction": 0.25}))
    b = cfg(policy=Policy.from_owner({"capital": 10_000}))
    assert a.trial_id() != b.trial_id() and a.effective_policy().cap_fraction == 0.25
    with pytest.raises(ValueError):
        cfg(W=20_000, policy=Policy.from_owner({"capital": 10_000}))


# ---- promotion cannot be faked -----------------------------------------------------------------------------

def test_a_hand_written_promotion_file_does_not_open_the_gate(root, tmp_path):
    eff = service.effective_policy(root)
    runs = tmp_path / "runs"
    (runs / "eval").mkdir(parents=True)
    (runs / "eval" / "dev.json").write_text(json.dumps({"trial_id": "t", "manifest_hash": "m", "promotion": {"verdict": "PROMOTED"}}))
    fake = {"promotion_id": "p1", "candidate": "A", "h": 20, "trial_id": "t", "manifest_hash": "m", "policy_digest": eff.digest(),
            "development_report": "eval/dev.json", "development_sha256": "0" * 64, "holdout_report": "eval/dev.json",
            "holdout_sha256": "0" * 64, "verdict": "PROMOTED"}
    atomic_json(runs / "promotions" / "p1.json", fake)
    rec, problems = registry.verified_promotion(runs, "A", 20, eff.digest())
    assert rec is None and "DEVELOPMENT_REPORT_HASH_MISMATCH" in problems
    out = decide.run(None, cfg(policy=eff), root=root, origin="cli")
    assert out["reasons"][0] == "MODEL_NOT_PROMOTED" and out["record"]["promotion_id"] is None
    assert "DEVELOPMENT_REPORT_HASH_MISMATCH" in out["record"]["promotion_check"]
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["decide", "--promoted"])  # the manual flag no longer exists


# ---- health is derived now, unknowns stay unknown ---------------------------------------------------------

def test_scheduler_health_comes_from_the_last_tick_not_the_saved_word(root, tmp_path):
    atomic_json(root / service.STATE_FILE, {"state": "RUNNING", "updated_at": at(5, 8).isoformat(), "interval_seconds": 60})
    st = webapp.status(root, tmp_path / "market", at(5, 10), calendar=CAL)
    sc = st["health"]["scheduler"]
    assert sc["status"] == "MISSED_HEARTBEATS" and sc["reported_state"] == "RUNNING" and sc["reported_state_current"] is False
    assert sc["current_silence_seconds"] == 7200 and st["service"]["state_is_current"] is False
    assert st["blockers"][0]["code"] == "SCHEDULER_NOT_RUNNING"
    atomic_json(root / service.STATE_FILE, {"state": "RUNNING", "updated_at": (at(5, 10) - timedelta(seconds=40)).isoformat()})
    assert webapp.status(root, tmp_path / "market", at(5, 10), calendar=CAL)["health"]["scheduler"]["status"] == "ALIVE"


def test_market_broker_and_calendar_states_are_explicit(root, tmp_path):
    sat = webapp.status(root, tmp_path / "market", at(7, 11), calendar=CAL)["health"]
    assert sat["market"]["status"] == "NO_SESSION" and sat["broker"]["status"] == "IDLE_BY_SCHEDULE"
    wed = webapp.status(root, tmp_path / "market", at(4, 10), calendar=CAL)
    assert wed["health"]["market"]["status"] == "OPEN" and wed["health"]["broker"]["status"] == "AUTH_REQUIRED"
    assert wed["service"]["calendar"]["discrepancies_checked"] is False  # nothing was compared: not "none"
    assert webapp.market_session(CAL, datetime(2031, 1, 6, 10, tzinfo=IST))["status"] == "UNKNOWN_CALENDAR"
    assert wed["health"]["actual_cash_usable"] == {"ok": False, "reasons": ["NO_COMPLETED_BATCH"]}
    assert wed["health"]["paper_decisions"]["eligible"] is False


def test_listings_are_split_by_date_and_route():
    assert webapp.listing_route("RE", "XYZ LTD") == "RIGHTS_ENTITLEMENT"
    assert webapp.listing_route("SM", "ABC LTD") == "SME_SEGMENT"
    assert webapp.listing_route("EQ", "NEW CO LTD") == "ROUTE_UNVERIFIED"


# ---- interrupted work is recovered, not stranded -------------------------------------------------------------

def test_running_requests_from_a_dead_scheduler_are_recovered(root, tmp_path, monkeypatch):
    folder = root / service.REQUESTS_DIR
    for name, kind in (("a_panel", "panel_build"), ("b_decide", "decide")):
        atomic_json(folder / f"{name}.json", {"id": name, "kind": kind, "args": {}, "state": "RUNNING", "attempt": 1,
                                              "worker": "previous-process", "started_at": at(5, 9).isoformat()})
    from marketlab.quant import panel as qpanel
    monkeypatch.setattr(qpanel, "build", lambda *a, **k: {"sessions_loaded": 0})
    ctx = service.Context(root, tmp_path / "market", [], calendar=CAL)
    started = service.process_requests(ctx, at(5, 10))
    ctx._request_thread.join(10)
    reqs = {r["id"]: r for r in service.list_requests(root)}
    assert started == ["a_panel"] and reqs["a_panel"]["state"] == "DONE" and reqs["a_panel"]["attempt"] == 2
    assert reqs["a_panel"]["history"][0]["reason"] == "SCHEDULER_RESTARTED"
    assert reqs["b_decide"]["state"] == "INTERRUPTED" and "not retried automatically" in reqs["b_decide"]["error"]
    atomic_json(folder / "a_panel.json", reqs["a_panel"] | {"state": "RUNNING", "worker": "another-dead-process"})
    service.recover_requests(service.Context(root, tmp_path / "market", [], calendar=CAL))
    assert service.read_json(folder / "a_panel.json", {})["state"] == "INTERRUPTED"  # attempts exhausted
