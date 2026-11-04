"""Login redirect capture, Kite error classification, partial collection and the terminal summary."""

import io
import json
import threading
import urllib.request
from email.message import Message
from urllib.error import HTTPError

import pytest

from marketlab import cli, kite
from marketlab.kite import AuthenticationRequired, KiteError, KiteReadOnly, PermissionDenied
from marketlab.store import Store


def _http_error(code, body):
    return HTTPError("https://api.kite.trade/x", code, "err", Message(), io.BytesIO(json.dumps(body).encode()))


class _RaisingOpener:
    def __init__(self, err):
        self.err = err

    def open(self, *a, **k):
        raise self.err


@pytest.mark.parametrize("code, body, exc, text", [
    (403, {"status": "error", "error_type": "TokenException", "message": "secret-ish"}, AuthenticationRequired,
     "TokenException"),
    (403, {"status": "error", "error_type": "PermissionException", "message": "x"}, PermissionDenied, "plan"),
    (403, {"status": "error"}, AuthenticationRequired, "HTTP 403"),
    (429, {"status": "error", "error_type": "NetworkException", "message": "x"}, KiteError, "NetworkException"),
    (400, {"status": "error", "error_type": "bad type!", "message": "x"}, KiteError, "HTTP 400;"),
])
def test_errors_are_classified_without_exposing_provider_messages(monkeypatch, code, body, exc, text):
    monkeypatch.setattr(kite, "build_opener", lambda *a: _RaisingOpener(_http_error(code, body)))
    monkeypatch.setattr(kite.time, "sleep", lambda _: None)
    with pytest.raises(exc) as e:
        KiteReadOnly("key", "tok").get("/portfolio/holdings")
    assert text in str(e.value) and "secret-ish" not in str(e.value) and "tok" not in str(e.value)


def test_expired_request_token_gets_a_specific_message(monkeypatch):
    err = _http_error(400, {"status": "error", "error_type": "InputException", "message": "Token is invalid"})
    monkeypatch.setattr(kite, "build_opener", lambda *a: _RaisingOpener(err))
    monkeypatch.setattr(kite.time, "sleep", lambda _: None)
    with pytest.raises(KiteError, match="request token may have expired"):
        KiteReadOnly("key").exchange_token("abcdef123", "s3cret")


def test_non_object_json_is_a_schema_error_not_a_crash(monkeypatch):
    class Resp:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"[1, 2]"

    class Opener:
        def open(self, *a, **k):
            return Resp()

    monkeypatch.setattr(kite, "build_opener", lambda *a: Opener())
    monkeypatch.setattr(kite.time, "sleep", lambda _: None)
    with pytest.raises(KiteError, match="unsuccessful"):  # previously an uncaught AttributeError
        KiteReadOnly("key", "tok").get("/portfolio/holdings")


def _hit(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.read().decode()


def test_callback_catcher_ignores_noise_and_returns_the_request_token():
    c = CallbackCatcherPort0()
    replies = []

    def browser():
        replies.append(_hit(c.port, "/favicon.ico"))
        replies.append(_hit(c.port, "/callback?action=login&type=login&status=success&request_token=Ab12Cd34Ef56"))

    t = threading.Thread(target=browser)
    t.start()
    try:
        assert c.wait(timeout=10) == "Ab12Cd34Ef56"
    finally:
        t.join(5)
        c.close()
    assert replies[0].startswith("Waiting") and replies[1].startswith("Kite login received")


def test_callback_catcher_rejects_failed_login_status():
    c = CallbackCatcherPort0()
    t = threading.Thread(target=lambda: _hit(c.port, "/?status=failed&request_token=Ab12Cd34Ef56"))
    t.start()
    try:
        assert c.wait(timeout=2) is None
    finally:
        t.join(5)
        c.close()


def CallbackCatcherPort0():
    return cli.CallbackCatcher(0)


def test_auth_uses_saved_key_redirect_token_and_never_saves_the_secret(tmp_path, monkeypatch):
    (tmp_path / cli.APP_FILE).write_text(json.dumps({"api_key": "publickey1", "redirect_port": 0}))
    prompts = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda p: prompts.append(p) or "the-secret")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)

    class FakeCatcher:
        port = 8766

        def __init__(self, port):
            pass

        def wait(self, timeout):
            return "Ab12Cd34Ef56"

        def close(self):
            pass

    monkeypatch.setattr(cli, "CallbackCatcher", FakeCatcher)
    seen = {}

    def fake_exchange(self, token, secret):
        seen.update(token=token, secret=secret, key=self.api_key)
        return {"access_token": "access-xyz"}

    monkeypatch.setattr(KiteReadOnly, "exchange_token", fake_exchange)
    cli.auth(tmp_path)
    assert seen == {"token": "Ab12Cd34Ef56", "secret": "the-secret", "key": "publickey1"}
    assert len(prompts) == 1 and "secret" in prompts[0]  # key came from the private app file
    saved = (tmp_path / "kite_session.json").read_text()
    assert "the-secret" not in saved and "access-xyz" in saved


class PlanLimitedKite:
    def get(self, path):
        if path == "/portfolio/holdings":
            return [{"tradingsymbol": "TESTA", "exchange": "NSE", "quantity": 10, "t1_quantity": 2,
                     "average_price": 100.5, "last_price": 110}]
        if path == "/portfolio/positions":
            return {"net": [], "day": []}
        if path == "/user/margins/equity":
            return {"net": 2500.75, "available": {"cash": 3000, "opening_balance": 3000, "live_balance": 2500.75},
                    "utilised": {"debits": 499.25}}
        if path.startswith("/instruments/"):
            raise PermissionDenied("plan")
        return []

    def quotes(self, symbols):
        raise PermissionDenied("plan")


def test_collection_continues_past_plan_limited_endpoints_and_summary_reads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "client", lambda root: PlanLimitedKite())
    cli.collect_once(tmp_path, ["NSE:TESTA"], instruments=True)
    status = json.loads((tmp_path / "status.json").read_text())["collection"]
    assert status["status"] == "COLLECTED_PARTIAL"
    assert set(status["unavailable"]) == {"quotes", "instruments_NSE", "instruments_BSE"}
    db = Store(tmp_path / "evidence.sqlite3")
    assert db.count() == 4
    db.close()
    text = cli.summary_text(tmp_path)
    # 12 shares: invested 12 x 100.50 = 1206.00, current 12 x 110 = 1320.00
    assert "TESTA" in text and "invested 1206.00" in text and "unrealised P&L 114.00" in text
    assert "cash 3000.00" in text and "used 499.25" in text
    assert "TESTA" not in (tmp_path / "status.json").read_text()


def test_expired_session_stops_collection(tmp_path, monkeypatch):
    class Expired:
        def get(self, path):
            raise AuthenticationRequired("expired")

    monkeypatch.setattr(cli, "client", lambda root: Expired())
    with pytest.raises(AuthenticationRequired):
        cli.collect_once(tmp_path, [])
