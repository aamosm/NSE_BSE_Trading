"""Dashboard endpoints, policy validation, request queue and scheduler-side execution."""
import json
import threading
import urllib.request
from datetime import date, datetime
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

from marketlab import service, webapp
from marketlab.common import IST

ENV = "KITE_API_KEY=pubkey\nKITE_API_SECRET=sec\nKITE_USER_ID=AB1234\n"


@pytest.fixture
def server(tmp_path, monkeypatch):
    root, market = tmp_path / "private", tmp_path / "market"
    root.mkdir()
    (root / ".env").write_text(ENV)
    monkeypatch.setattr(webapp, "RUNS", tmp_path / "runs")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.make_handler(webapp.App(root, market)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root, market, tmp_path
    srv.shutdown()
    srv.server_close()


def call(base, path, method="GET", headers=None, data=None):
    req = urllib.request.Request(base + path, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body.decode(errors="replace")


ACT = {"X-MarketLab-Action": "1", "Content-Type": "application/json"}


def test_read_endpoints_degrade_gracefully_without_data(server):
    base, *_ = server
    assert call(base, "/api/data")[1] == {"sources": {}, "panel": None, "master": [], "missing_recent": {}}
    assert call(base, "/api/universe")[1] == {"error": "PANEL_NOT_BUILT"}
    assert call(base, "/api/evaluation")[1] == {"reports": []}
    assert call(base, "/api/decision")[1] == {"decision": None, "available": [], "diagnostics": None}
    code, r = call(base, "/api/research")
    assert code == 200 and r["provider"] == "none"
    code, c = call(base, "/api/config")
    assert code == 200 and c["policy"]["capital"] == 10000.0 and "evaluate" in c["request_kinds"]
    s = call(base, "/api/status")[1]
    assert s["policy"]["K"] is None and s["policy_effective"]["K"] == 2 and s["policy_effective"]["cap_rupees"] == 5000.0
    assert s["latest_decision"] is None and s["live_orders"] is False and c["candidates"]["B"]["implemented"] is False


def test_policy_edits_are_validated_and_bounded(server):
    base, root, *_ = server
    assert call(base, "/api/config", "POST", data=b"{}")[0] == 403  # header required
    code, r = call(base, "/api/config", "POST", ACT, json.dumps({"capital": 50000, "K": 3, "symbols": ["INFY", "TCS"]}).encode())
    assert code == 200 and r["policy"]["capital"] == 50000.0 and r["policy"]["K"] == 3 and r["policy"]["symbols"] == ["INFY", "TCS"]
    assert service.policy(root)["K"] == 3
    for bad in ({"K": 50}, {"capital": 10}, {"candidate": "Z"}, {"symbols": ["bad symbol!"]}, {"unknown": 1}, {"h": "x"}):
        code, r = call(base, "/api/config", "POST", ACT, json.dumps(bad).encode())
        assert code == 400 and "error" in r, bad
    assert call(base, "/api/config", "POST", ACT, b"not json")[0] == 400
    code, r = call(base, "/api/config", "POST", ACT, json.dumps({"families": {"B": True}}).encode())
    assert code == 400 and "UNIMPLEMENTED" in r["error"]  # family B has no evidence path
    code, r = call(base, "/api/config", "POST", ACT, json.dumps({"families": {"A": False, "Z": True}}).encode())
    assert code == 200 and r["policy"]["families"] == {"A": False, "B": False, "C": False}
    code, r = call(base, "/api/config", "POST", ACT, json.dumps({"K": None, "cap_fraction": 0.25}).encode())
    assert code == 200 and r["policy"]["K"] is None and service.effective_policy(root).cap_fraction == 0.25


def test_requests_are_queued_for_the_scheduler_and_executed_there(server, monkeypatch):
    base, root, market, tmp = server
    assert call(base, "/api/request", "POST", ACT, json.dumps({"kind": "orders"}).encode())[0] == 400
    code, r = call(base, "/api/request", "POST", ACT, json.dumps({"kind": "prepare", "args": {"date": "2026-11-05"}}).encode())
    assert code == 200 and r["state"] == "QUEUED" and r["args"] == {"date": "2026-11-05"}
    listed = call(base, "/api/requests")[1]["requests"]
    assert listed[0]["id"] == r["id"] and listed[0]["state"] == "QUEUED"
    ctx = service.Context(root, market, [], calendar=__import__("marketlab.rules", fromlist=["MarketCalendar"]).MarketCalendar())
    monkeypatch.setattr(service, "job_prepare", lambda c, a: f"OK:{a['day']}")
    started = service.process_requests(ctx, datetime(2026, 11, 5, 10, tzinfo=IST))
    assert started == [r["id"]]
    ctx._request_thread.join(10)
    done = service.list_requests(root)[0]
    assert done["state"] == "DONE" and done["result"] == "OK:2026-11-05"
    assert service.process_requests(ctx) == []  # nothing left


def test_failed_request_is_recorded_not_raised(server, monkeypatch):
    base, root, market, tmp = server
    call(base, "/api/request", "POST", ACT, json.dumps({"kind": "panel_build"}).encode())
    ctx = service.Context(root, market, [], calendar=__import__("marketlab.rules", fromlist=["MarketCalendar"]).MarketCalendar())
    from marketlab.quant import panel
    monkeypatch.setattr(panel, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    service.process_requests(ctx)
    ctx._request_thread.join(10)
    rec = service.list_requests(root)[0]
    assert rec["state"] == "FAILED" and rec["error"].startswith("RuntimeError")


def test_evaluation_and_decision_views_read_run_files(server):
    base, root, market, tmp = server
    (tmp / "runs" / "eval").mkdir(parents=True)
    (tmp / "runs" / "eval" / "A.h20.abc.json").write_text(json.dumps({"trial_id": "A.h20.abc", "folds_done": 2, "n_trades": 5,
                                                                      "net_rupees_total": -12.5, "folds": [{"simulation": {"trades": list(range(300))}}],
                                                                      "pooled": {"sharpe_per_trade": -0.1}}))
    from marketlab import decisions
    entry = decisions.record(root, {"day": "2026-11-05", "action": "WAIT", "reasons": ["MODEL_NOT_PROMOTED"], "forecasts": 2,
                                    "candidate": "A", "h": 20}, origin="cli", diagnostics={"forecasts": [1, 2]})
    reps = call(base, "/api/evaluation")[1]["reports"]
    assert reps[0]["trial_id"] == "A.h20.abc" and reps[0]["net_rupees_total"] == -12.5
    full = call(base, "/api/evaluation?trial=A.h20.abc")[1]
    assert len(full["folds"][0]["simulation"]["trades"]) == 200  # capped
    assert call(base, "/api/evaluation?trial=../../etc")[1] == {"error": "NOT_FOUND"}
    d = call(base, "/api/decision")[1]
    assert d["decision"]["action"] == "WAIT" and d["available"] == [entry["decision_id"]] and d["diagnostics"]["forecasts"] == [1, 2]
    st = call(base, "/api/status")[1]
    assert st["latest_decision"]["decision_id"] == st["decisions"][0]["decision_id"] == entry["decision_id"]
    assert st["latest_decision"]["forecasts"] == 2 and st["latest_decision"]["integrity"] == "OK"
