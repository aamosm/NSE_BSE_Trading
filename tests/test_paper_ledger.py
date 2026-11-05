"""Forward paper ledger: PAPER_PLAN only with a verified promotion; orders frozen in the decision record; fills at
the next stored open by the replay ledger; deterministic rebuilds; write-once snapshots that expose revisions."""
import json
import sqlite3

import pytest

from marketlab import decisions
from marketlab.quant import decide, evaluate, paper, registry
from marketlab.quant.allocate import Policy
from marketlab.quant.universe import ScreenPolicy
from synthetic import WeekdayCalendar, make_panel

CAL = WeekdayCalendar()


@pytest.fixture(scope="module")
def panel(tmp_path_factory):
    p = make_panel(tmp_path_factory.mktemp("paper") / "p.sqlite3", n=420, n_stocks=30, bonus_at=10_000)
    yield p
    p.close()


def cfg():
    return evaluate.Config(h=20, train_sessions=200, screen=ScreenPolicy(v_min=1, W=10_000), policy=Policy.for_capital(10_000))


def promote(runs, c):
    """A promotion record whose cited reports hash correctly (the gate itself is tested in test_replay_correctness)."""
    crit = {k: True for k in ("verified_folds_exist", "net_positive_pooled", "dsr_95")} | {"holdout_net_positive": None}
    pol = c.effective_policy().digest()
    reps = {"eval": {"trial_id": "A.h20.t", "manifest_hash": "m", "policy_digest": pol, "holdout": False, "promotion": {"criteria": crit}},
            "holdout": {"trial_id": "A.h20.t", "manifest_hash": "m", "policy_digest": pol, "holdout": True, "net_rupees_total": 50.0}}
    for kind, rep in reps.items():
        (runs / kind / "A.h20.t").mkdir(parents=True, exist_ok=True)
        (runs / kind / "A.h20.t" / "r.json").write_text(json.dumps(rep))
    return registry.write_promotion(runs, runs / "eval/A.h20.t/r.json", runs / "holdout/A.h20.t/r.json", "A", 20)


def test_without_a_promotion_there_is_no_paper_account(panel, tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    days = panel.sessions()
    out = decide.run(panel.view(days[399]), cfg(), root=root, origin="cli", calendar=CAL, bootstrap=0)
    assert out["action"] == "WAIT" and out["reasons"][0] == "MODEL_NOT_PROMOTED"
    assert paper.status(panel, CAL, root, 10_000)["state"] == "NO_PAPER_ORDERS_YET"


def test_promoted_orders_fill_at_the_next_open_and_rebuilds_are_deterministic(panel, tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    c = cfg()
    assert promote(decisions.runs_dir(root), c)
    days = panel.sessions()
    d0 = days[399]
    out = decide.run(panel.view(d0), c, root=root, origin="cli", calendar=CAL, bootstrap=0)
    rec = out["record"]
    assert out["action"] == "PAPER_PLAN" and rec["promotion_id"] and rec["orders"]["intents"]
    for it in rec["orders"]["intents"]:
        assert it["decision_day"] == d0.isoformat() and float(it["reserved"]) <= 8_000  # cash blocked at the limit
    built = paper.rebuild(panel, CAL, root, days[402])
    led = built["ledger"]
    ev = [e for e in led.events if e["day"] == days[400].isoformat()]
    assert ev and all(e["event"] in ("FILLED", "REJECTED_GAP", "FILL_DEFERRED", "PROCEEDS_SETTLED") for e in ev)
    filled = {e["isin"] for e in ev if e["event"] == "FILLED"}
    assert filled == set(led.lots) and led.nav[0]["day"] == d0.isoformat() and led.nav[0]["nav"] == 10_000.0
    first = paper.snapshot(root, built)
    assert first["status"] == "WRITTEN"
    assert paper.snapshot(root, paper.rebuild(panel, CAL, root, days[402]))["status"] == "UNCHANGED"
    # the next decision plans against the real holdings: no second intent for a held security, fewer free slots
    nxt = decide.run(panel.view(days[400]), c, root=root, origin="cli", calendar=CAL, bootstrap=0)["record"]
    held = {p["isin"] for p in nxt["ledger_before"]["positions"]}
    assert held == filled and not ({i["isin"] for i in (nxt.get("orders") or {}).get("intents", [])} & held)
    st = paper.status(panel, CAL, root, 10_000)
    assert st["state"] == "ACTIVE" and st["since"] == d0.isoformat()


def test_a_revised_input_file_is_reported_not_overwritten(tmp_path):
    p = make_panel(tmp_path / "r.sqlite3", n=420, n_stocks=30, bonus_at=10_000)
    root = tmp_path / "private"
    root.mkdir()
    c = cfg()
    promote(decisions.runs_dir(root), c)
    days = p.sessions()
    decide.run(p.view(days[399]), c, root=root, origin="cli", calendar=CAL, bootstrap=0)
    built = paper.rebuild(p, CAL, root, days[402])
    assert paper.snapshot(root, built)["status"] == "WRITTEN"
    with sqlite3.connect(tmp_path / "r.sqlite3") as con:  # a stored price changes after the fact
        con.execute("UPDATE bars SET close = close * 1.1 WHERE day = ?", (days[401].isoformat(),))
    again = paper.snapshot(root, paper.rebuild(p, CAL, root, days[402]))
    assert again["status"] == "REVISED" and again["stored_sha256"] != again["rebuilt_sha256"]
    p.close()
