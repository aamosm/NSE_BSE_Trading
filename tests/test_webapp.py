"""Phone app server: login round trip, route allowlist, CSRF, identity header, caching, separation of data."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from marketlab import login, service, webapp, webassets
from marketlab.kite import KiteReadOnly

ENV = ("KITE_API_KEY=pubkey\nKITE_API_SECRET=sec\nKITE_USER_ID=AB1234\n"
       "KITE_REDIRECT_URL=https://box.tail1234.ts.net/kite/callback\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@pytest.fixture
def server(tmp_path, monkeypatch):
    root, market = tmp_path / "private", tmp_path / "market"
    root.mkdir()
    (root / ".env").write_text(ENV)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.make_handler(webapp.App(root, market)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(KiteReadOnly, "exchange_token",
                        lambda self, token, secret: {"access_token": "acc-1", "user_id": "AB1234"})
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()
    srv.server_close()


def call(base, path, method="GET", headers=None, data=None):
    req = urllib.request.Request(base + path, method=method, headers=headers or {}, data=data)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_shell_and_status_are_served_with_strict_headers(server):
    base, _ = server
    code, h, body = call(base, "/")
    assert code == 200 and "script-src 'self'" in h["Content-Security-Policy"] and h["Referrer-Policy"] == "no-referrer"
    code, h, body = call(base, "/api/status")
    s = json.loads(body)
    assert code == 200 and h["Cache-Control"] == "no-store" and s["live_orders"] is False
    assert s["actual"]["batch"] is None and s["simulated"]["kind"] == "SIMULATED_PAPER"
    assert s["simulated"]["cash"] is None and s["simulated"]["state"] == "FORWARD_PAPER_LEDGER_NOT_BUILT"  # no constants
    codes = [b["code"] for b in s["blockers"]]
    assert s["session"]["state"] == "AUTH_REQUIRED" and codes[:2] == ["SCHEDULER_NOT_RUNNING", "AUTH_REQUIRED"]
    assert s["health"]["scheduler"]["status"] == "NEVER_STARTED" and s["health"]["web"] == "REACHABLE"


def test_login_round_trip_saves_session_and_state_is_single_use(server):
    base, root = server
    code, h, _ = call(base, "/login/start")
    assert code == 302 and h["Cache-Control"] == "no-store"
    loc = urlsplit(h["Location"])
    q = parse_qs(loc.query)
    assert loc.netloc == "kite.zerodha.com" and q["api_key"] == ["pubkey"]
    state = parse_qs(q["redirect_params"][0])["state"][0]
    assert state not in (root / login.STATE_FILE).read_text()  # stored hashed only
    cb = f"/kite/callback?action=login&type=login&status=success&request_token=Ab12Cd34Ef56&state={state}"
    code, h, body = call(base, cb)
    assert code == 200 and b"Kite login complete" in body and h["Cache-Control"] == "no-store"
    saved = json.loads((root / login.SESSION_FILE).read_text())
    assert saved["access_token"] == "acc-1" and "sec" not in json.dumps(saved)
    assert json.loads(call(base, "/api/status")[2])["session"]["state"] == "AUTHENTICATED"
    code, _, body = call(base, cb)  # replay
    assert code == 400 and b"LOGIN_STATE_INVALID_OR_EXPIRED" in body


def test_callback_on_another_path_or_without_state_is_refused(server):
    base, root = server
    assert call(base, "/kite/callback/?status=success&request_token=Ab12Cd34Ef56&state=" + "x" * 43)[0] == 404
    code, _, body = call(base, "/kite/callback?status=success&request_token=Ab12Cd34Ef56")
    assert code == 400 and b"LOGIN_STATE_INVALID" in body
    assert not (root / login.SESSION_FILE).exists()


def test_wrong_account_is_not_saved(server, monkeypatch):
    base, root = server
    monkeypatch.setattr(KiteReadOnly, "exchange_token", lambda self, t, s: {"access_token": "x", "user_id": "ZZ9"})
    state = login.StateBook(root / login.STATE_FILE).issue()
    code, _, body = call(base, f"/kite/callback?status=success&request_token=Ab12Cd34Ef56&state={state}")
    assert code == 502 and b"not KITE_USER_ID" in body and not (root / login.SESSION_FILE).exists()


@pytest.mark.parametrize("path, method, code", [
    ("/orders", "POST", 405), ("/api/analysis/pause", "PUT", 405), ("/orders", "DELETE", 405),
    ("/api/orders", "GET", 404), ("/../private/.env", "GET", 404),
])
def test_no_order_or_unlisted_routes(server, path, method, code):
    base, _ = server
    assert call(base, path, method, data=b"" if method != "GET" else None)[0] == code


def test_pause_requires_the_action_header(server):
    base, root = server
    assert call(base, "/api/analysis/pause", "POST", data=b"")[0] == 403
    code, _, body = call(base, "/api/analysis/pause", "POST", headers={"X-MarketLab-Action": "1"}, data=b"")
    assert code == 200 and json.loads(body)["analysis_paused"] is True
    assert service.control(root)["analysis_paused"] is True
    call(base, "/api/analysis/resume", "POST", headers={"X-MarketLab-Action": "1"}, data=b"")
    assert service.control(root)["analysis_paused"] is False


def test_tailnet_identity_is_enforced_when_configured(server):
    base, root = server
    (root / ".env").write_text(ENV + "MARKETLAB_TAILNET_USER=owner@example.com\n")
    assert call(base, "/health")[0] == 200
    assert call(base, "/api/status")[0] == 403
    assert call(base, "/api/status", headers={"Tailscale-User-Login": "other@example.com"})[0] == 403
    assert call(base, "/api/status", headers={"Tailscale-User-Login": "owner@example.com"})[0] == 200


def test_service_worker_never_caches_api_or_login():
    sw = webassets.SERVICE_WORKER
    assets = sw.split("const ASSETS = [")[1].split("]")[0]
    assert "/api" not in assets and "/login" not in assets and "callback" not in assets
    assert "network only" in sw


def test_icons_are_valid_pngs():
    png = webassets.icon_png(192)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 192


def test_server_refuses_non_loopback_binding(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        webapp.serve(tmp_path, tmp_path, 0, host="0.0.0.0")


def test_the_server_names_the_code_it_runs(server):
    import subprocess
    from pathlib import Path
    base, _ = server
    code, _, body = call(base, "/api/version")
    v = json.loads(body)
    pkg = Path(__file__).resolve().parents[1] / "src" / "marketlab"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pkg, capture_output=True, text=True).stdout.strip()
    assert code == 200 and Path(v["code_path"]) == pkg and v["git_head"] == head and len(v["source_digest_now"]) == 64
    h = json.loads(call(base, "/health")[2])
    assert h["git_head"] == head and h["source_changed_since_start"] is False
