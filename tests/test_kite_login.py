"""Login redirect capture, Kite error classification, partial collection and the terminal summary."""

import io
import json
import threading
import urllib.request
from email.message import Message
from urllib.error import HTTPError

import pytest

from marketlab import cli, kite, login
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
    (400, {"status": "error", "error_type": "bad type!", "message": "x"}, KiteError, "HTTP 400 (UnknownErrorType)"),
    (400, {"status": "error", "message": "x"}, KiteError, "HTTP 400;"),
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

        sent = False

        def read(self, n):
            if self.sent:
                return b""
            self.sent = True
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


def test_callback_catcher_requires_exact_path_and_single_use_state():
    states = login.StateBook()
    state = states.issue()
    c = cli.CallbackCatcher(0, "/kite/callback", states)
    replies = []

    def browser():
        replies.append(_hit(c.port, "/favicon.ico"))
        replies.append(_hit(c.port, "/other?status=success&request_token=Ab12Cd34Ef56&state=" + state))
        replies.append(_hit(c.port, "/kite/callback?status=success&request_token=Ab12Cd34Ef56&state=" + "x" * 43))
        replies.append(_hit(c.port, "/kite/callback?action=login&type=login&status=success"
                                    "&request_token=Ab12Cd34Ef56&state=" + state))

    t = threading.Thread(target=browser)
    t.start()
    try:
        assert c.wait(timeout=10) == "Ab12Cd34Ef56"
    finally:
        t.join(5)
        c.close()
    assert "LOGIN_WRONG_PATH" in replies[0] and "LOGIN_WRONG_PATH" in replies[1]
    assert "LOGIN_STATE_INVALID_OR_EXPIRED" in replies[2] and replies[3].startswith("Kite login received")
    assert not states.consume(state)  # single use


def test_callback_catcher_rejects_failed_login_status():
    states = login.StateBook()
    state = states.issue()
    c = cli.CallbackCatcher(0, "/", states)
    t = threading.Thread(target=lambda: _hit(c.port, "/?status=failed&request_token=Ab12Cd34Ef56&state=" + state))
    t.start()
    try:
        assert c.wait(timeout=2) is None
    finally:
        t.join(5)
        c.close()


def test_idle_connection_does_not_block_the_catcher():
    import socket
    states = login.StateBook()
    state = states.issue()
    c = cli.CallbackCatcher(0, "/", states)
    idle = socket.create_connection(("127.0.0.1", c.port))  # connects, never sends a request
    t = threading.Thread(target=lambda: _hit(c.port, "/?status=success&request_token=Ab12Cd34Ef56&state=" + state))
    t.start()
    try:
        assert c.wait(timeout=20) == "Ab12Cd34Ef56"
    finally:
        t.join(25)
        idle.close()
        c.close()


class PlanLimitedKite:
    def get(self, path):
        if path == "/portfolio/holdings":
            return [{"tradingsymbol": "TESTA", "exchange": "NSE", "quantity": 10, "t1_quantity": 2,
                     "average_price": 100.5, "last_price": 110}]
        if path == "/portfolio/positions":
            return {"net": [{"tradingsymbol": "TESTB", "product": "MIS", "quantity": 0, "buy_quantity": 5,
                             "sell_quantity": 5, "average_price": 0, "last_price": 51, "pnl": -12.5}], "day": []}
        if path == "/trades":
            return [{"tradingsymbol": "TESTB", "transaction_type": "BUY", "product": "MIS", "quantity": 3,
                     "average_price": 50}, {"tradingsymbol": "TESTB", "transaction_type": "BUY", "product": "MIS",
                                            "quantity": 2, "average_price": 50.5}]
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
    assert db.count() == 5  # four account kinds plus the completed-batch record
    db.close()
    text = cli.summary_text(tmp_path)
    # 12 shares: invested 12 x 100.50 = 1206.00, current 12 x 110 = 1320.00
    assert "TESTA" in text and "invested 1206.00" in text and "unrealised P&L 114.00" in text
    assert "cash 3000.00" in text and "used 499.25" in text
    assert "Total position P&L -12.50" in text
    assert "fills   2  qty      5  value       251.00" in text  # 3 x 50 + 2 x 50.50
    assert "TESTA" not in (tmp_path / "status.json").read_text()


def test_expired_session_stops_collection(tmp_path, monkeypatch):
    class Expired:
        def get(self, path):
            raise AuthenticationRequired("expired")

    monkeypatch.setattr(cli, "client", lambda root: Expired())
    with pytest.raises(AuthenticationRequired):
        cli.collect_once(tmp_path, [])



def _fake_login(monkeypatch, user_id="AB1234"):
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    seen = {}

    class FakeCatcher:
        port = 8766

        def __init__(self, port, path, states):
            seen.update(port=port, path=path)
            self.states = states

        def wait(self, timeout):
            # The URL opened in the browser carries a state; simulate Kite echoing it back.
            return "Ab12Cd34Ef56" if self.states._mem else None

        def close(self):
            pass

    monkeypatch.setattr(cli, "CallbackCatcher", FakeCatcher)

    def fake_exchange(self, token, secret):
        seen.update(secret=secret, key=self.api_key, token=token)
        return {"access_token": "access-xyz", "user_id": user_id}

    monkeypatch.setattr(KiteReadOnly, "exchange_token", fake_exchange)
    monkeypatch.setattr(cli.getpass, "getpass", lambda p: pytest.fail("must not prompt when the env file has values"))
    return seen


def test_auth_reads_private_env_and_checks_the_account(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# private\nKITE_API_KEY=envkey\nKITE_API_SECRET='envsecret'\nKITE_USER_ID=AB1234\n")
    seen = _fake_login(monkeypatch)
    cli.auth(tmp_path)
    assert seen == {"secret": "envsecret", "key": "envkey", "token": "Ab12Cd34Ef56", "port": 8766, "path": "/"}
    saved = (tmp_path / "kite_session.json").read_text()
    assert "envsecret" not in saved and "access-xyz" in saved and "AB1234" not in saved


def test_auth_uses_the_registered_redirect_port_and_path(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("KITE_API_KEY=k\nKITE_API_SECRET=s\nKITE_USER_ID=AB1234\n"
                                   "KITE_REDIRECT_URL=http://127.0.0.1:8765/kite/callback\n")
    seen = _fake_login(monkeypatch)
    cli.auth(tmp_path)
    assert seen["port"] == 8765 and seen["path"] == "/kite/callback"


def test_auth_refuses_a_different_account(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("KITE_API_KEY=k\nKITE_API_SECRET=s\nKITE_USER_ID=AB1234\n")
    _fake_login(monkeypatch, user_id="ZZ9999")
    with pytest.raises(KiteError, match="not KITE_USER_ID"):
        cli.auth(tmp_path)
    assert not (tmp_path / "kite_session.json").exists()


@pytest.mark.parametrize("missing", ["KITE_API_KEY", "KITE_API_SECRET", "KITE_USER_ID"])
def test_auth_requires_key_secret_and_expected_account(tmp_path, monkeypatch, missing):
    values = {"KITE_API_KEY": "k", "KITE_API_SECRET": "s", "KITE_USER_ID": "AB1234"}
    del values[missing]
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    _fake_login(monkeypatch)
    with pytest.raises(ValueError, match=missing):
        cli.auth(tmp_path)


@pytest.mark.parametrize("line", ["KITE_PASSWORD=x", "kite_totp_secret=x", "ZERODHA_PIN=1"])
def test_env_file_with_a_login_password_or_otp_is_refused(tmp_path, line):
    (tmp_path / ".env").write_text("KITE_API_KEY=k\n" + line + "\n")
    with pytest.raises(ValueError, match="must not be stored"):
        cli.load_env(tmp_path)
