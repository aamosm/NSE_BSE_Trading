"""Login state, redirect checks, token expiry, env allowlist, error labels and read deadlines."""
import ast
import io
import json
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from marketlab import kite, login
from marketlab.common import IST
from marketlab.kite import KiteError, KiteReadOnly

T = datetime(2026, 11, 5, 9, 0, tzinfo=IST)
TOKEN = "Ab12Cd34Ef56"


def target(state, path="/kite/callback", extra=""):
    return f"{path}?action=login&type=login&status=success&request_token={TOKEN}&state={state}{extra}"


def test_state_is_single_use_and_expires(tmp_path):
    book = login.StateBook(tmp_path / login.STATE_FILE)
    s1, s2 = book.issue(T), book.issue(T)
    assert login.check_redirect(target(s1), "/kite/callback", book, T + timedelta(minutes=9)) == TOKEN
    with pytest.raises(login.LoginRejected, match="STATE_INVALID_OR_EXPIRED"):
        login.check_redirect(target(s1), "/kite/callback", book, T + timedelta(minutes=9))  # replay
    with pytest.raises(login.LoginRejected, match="STATE_INVALID_OR_EXPIRED"):
        login.check_redirect(target(s2), "/kite/callback", book, T + timedelta(minutes=11))  # expired
    stored = (tmp_path / login.STATE_FILE).read_text()
    assert s1 not in stored and s2 not in stored  # only hashes on disk


def test_persisted_state_survives_a_restart(tmp_path):
    s = login.StateBook(tmp_path / login.STATE_FILE).issue(T)
    fresh = login.StateBook(tmp_path / login.STATE_FILE)
    assert login.check_redirect(target(s), "/kite/callback", fresh, T + timedelta(minutes=1)) == TOKEN


def test_only_a_few_pending_states_are_kept():
    book = login.StateBook()
    states = [book.issue(T + timedelta(seconds=i)) for i in range(login.MAX_PENDING + 2)]
    assert not book.consume(states[0], T + timedelta(minutes=1))
    assert book.consume(states[-1], T + timedelta(minutes=1))


@pytest.mark.parametrize("bad, label", [
    (lambda s: target(s, path="/kite/callback/"), "WRONG_PATH"),
    (lambda s: target(s, path="/"), "WRONG_PATH"),
    (lambda s: target(s, extra="&state=" + s), "DUPLICATE_PARAMETER"),
    (lambda s: target(s).replace("status=success", "status=cancelled"), "NOT_SUCCESSFUL"),
    (lambda s: target(s).replace(TOKEN, "bad token!"), "TOKEN_MISSING"),
    (lambda s: target(s).replace("&state=" + s, ""), "STATE_INVALID"),
    (lambda s: target("A" * 43), "STATE_INVALID"),
])
def test_redirect_checks(bad, label):
    book = login.StateBook()
    s = book.issue(T)
    with pytest.raises(login.LoginRejected, match=label):
        login.check_redirect(bad(s), "/kite/callback", book, T)


def test_login_url_sends_state_through_redirect_params():
    url = login.login_url("pubkey", "S" * 43)
    q = parse_qs(urlsplit(url).query)
    assert url.startswith("https://kite.zerodha.com/connect/login?")
    assert q["v"] == ["3"] and q["api_key"] == ["pubkey"] and parse_qs(q["redirect_params"][0]) == {"state": ["S" * 43]}


@pytest.mark.parametrize("at, expected", [
    (datetime(2026, 11, 5, 1, 0, tzinfo=IST), datetime(2026, 11, 5, 6, 0, tzinfo=IST)),  # after midnight: same day
    (datetime(2026, 11, 5, 6, 0, tzinfo=IST), datetime(2026, 11, 6, 6, 0, tzinfo=IST)),
    (datetime(2026, 11, 5, 23, 59, tzinfo=IST), datetime(2026, 11, 6, 6, 0, tzinfo=IST)),
])
def test_access_token_expiry_is_the_next_6am(at, expected):
    assert login.next_expiry(at) == expected


def test_complete_login_verifies_account_and_never_stores_secret_or_identity(tmp_path):
    env = {"KITE_API_KEY": "k", "KITE_API_SECRET": "sec", "KITE_USER_ID": "AB1234"}

    class Fake:
        def __init__(self, key):
            pass

        def exchange_token(self, token, secret):
            assert token == TOKEN and secret == "sec"
            return {"access_token": "acc", "user_id": "AB1234", "email": "x@example.com"}

    out = login.complete_login(tmp_path, env, TOKEN, kite_factory=Fake, at=T)
    saved = json.loads((tmp_path / login.SESSION_FILE).read_text())
    assert set(saved) == {"api_key", "access_token", "login_at", "expires_at"}
    assert "acc" not in json.dumps(out) and login.session_status(tmp_path, T)["state"] == "AUTHENTICATED"
    assert login.session_status(tmp_path, T + timedelta(days=1))["reason"] == "SESSION_EXPIRED"


def test_session_status_unreadable_file_requires_login(tmp_path):
    (tmp_path / login.SESSION_FILE).write_text("{broken")
    assert login.session_status(tmp_path)["reason"] == "SESSION_FILE_UNREADABLE"


@pytest.mark.parametrize("line, match", [
    ("KITE_PASSWORD=x", "must not be stored"), ("kite_totp_secret=x", "must not be stored"),
    ("ZERODHA_PIN=1", "must not be stored"), ("MY_LOGIN=hunter2", "unknown key"),
    ("SECRET2=x", "unknown key"), ("no equals sign", "not KEY=VALUE"),
])
def test_env_file_refuses_passwords_and_unknown_keys(tmp_path, line, match):
    (tmp_path / ".env").write_text("KITE_API_KEY=k\n" + line + "\n")
    with pytest.raises(ValueError, match=match):
        login.load_env(tmp_path)


def test_allowed_env_keys_are_not_themselves_refused():
    assert not [k for k in login.ALLOWED_ENV if any(w in k for w in login.FORBIDDEN_ENV)]


@pytest.mark.parametrize("url, ok", [
    ("http://127.0.0.1:8766/", True), ("https://box.tail1234.ts.net/kite/callback", True),
    ("http://box.tail1234.ts.net/kite/callback", False), ("https://x/cb?a=1", False),
    ("ftp://127.0.0.1/", False), ("https://user:pw@x.ts.net/cb", False),
])
def test_redirect_url_validation(url, ok):
    env = {"KITE_REDIRECT_URL": url}
    if ok:
        assert login.redirect_url(env) == url
    else:
        with pytest.raises(ValueError):
            login.redirect_url(env)


class _Opener:
    def __init__(self, err):
        self.err = err

    def open(self, *a, **k):
        raise self.err


@pytest.mark.parametrize("kind, shown", [
    ("GeneralException", "(GeneralException)"), ("Arbitrary<script>", "(UnknownErrorType)"),
    ("OrderException", "(OrderException)"), (12, "(UnknownErrorType)"), (["x"], "(UnknownErrorType)"),
    (None, "HTTP 500;"),
])
def test_only_enumerated_error_types_are_echoed(monkeypatch, kind, shown):
    body = json.dumps({"status": "error", "error_type": kind, "message": "leaky detail"}).encode()
    err = HTTPError("https://api.kite.trade/x", 500, "e", Message(), io.BytesIO(body))
    monkeypatch.setattr(kite, "build_opener", lambda *a: _Opener(err))
    monkeypatch.setattr(kite.time, "sleep", lambda _: None)
    with pytest.raises(KiteError) as e:
        KiteReadOnly("key", "tok").get("/portfolio/holdings")
    assert shown in str(e.value) and "leaky" not in str(e.value)


def test_read_deadline_stops_a_trickling_response():
    class Trickle:
        def read(self, n):
            return b"x"
    ticks = iter(range(0, 1000, 10))
    with pytest.raises(KiteError, match="read deadline"):
        kite.read_bounded(Trickle(), deadline=90, clock=lambda: next(ticks))


def test_read_size_limit():
    with pytest.raises(KiteError, match="limit"):
        kite.read_bounded(io.BytesIO(b"x" * 200), limit=100)
    assert kite.read_bounded(io.BytesIO(b"abc")) == b"abc"


RESEARCH_LAYER = ["research.py", "costs.py", "backtest.py", "audit.py", "experiments.py", "account.py",
                  "rules", "metrics"]


def test_research_and_model_layer_never_imports_a_broker_client():
    root = Path(kite.__file__).parent
    files = [p for name in RESEARCH_LAYER for p in ([root / name] if name.endswith(".py") else (root / name).rglob("*.py"))]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, (ast.Import, ast.ImportFrom)) else []
            module = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            assert "kite" not in module and not any("kite" in n or "urllib" in n for n in names), path
            assert "urllib" not in module and "http" not in module, path
