"""Official Kite login, shared by the terminal (`auth`) and the phone app.

Flow: browser -> kite.zerodha.com login (the owner types password/app code there) -> Kite redirects
to the registered URL with ``request_token`` and our ``state`` (sent via Kite's documented
``redirect_params``) -> this module checks path, state and token shape -> server-side token exchange
-> the logged-in account must equal ``KITE_USER_ID`` -> only the access token is saved.

Login state is random, single-use and expires after ``STATE_TTL``. Only its SHA-256 is kept on disk.
No password, PIN, OTP, TOTP seed or browser cookie is ever read, stored or automated.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .common import IST, atomic_json, now, timestamp
from .kite import KiteError, KiteReadOnly

ENV_FILE = ".env"
SESSION_FILE = "kite_session.json"
STATE_FILE = "login_states.json"
STATE_TTL = timedelta(minutes=10)
MAX_PENDING = 5
DEFAULT_REDIRECT = "http://127.0.0.1:8766/"
REQUEST_TOKEN = re.compile(r"[A-Za-z0-9]{6,64}")
STATE = re.compile(r"[A-Za-z0-9_-]{32,64}")
LOGIN_HOST = "https://kite.zerodha.com/connect/login"

# Only these keys may appear in the private env file. Anything else is refused so that a password
# cannot be parked there under an invented name. Names containing a FORBIDDEN word are refused first,
# with an explicit message. Neither check can detect a password typed as the *value* of an allowed key.
ALLOWED_ENV = frozenset({
    "KITE_API_KEY", "KITE_API_SECRET", "KITE_USER_ID", "KITE_REDIRECT_URL",
    "MARKETLAB_HEARTBEAT_URL", "MARKETLAB_ALERT_URL", "MARKETLAB_TAILNET_USER",
})
FORBIDDEN_ENV = ("PASSWORD", "PASSWD", "PIN", "TOTP", "OTP")


class LoginRejected(KiteError):
    """The redirect did not satisfy path/state/token checks. Its label is safe to show."""


def load_env(root: Path) -> dict:
    path = root / ENV_FILE
    env = {}
    if not path.exists():
        return env
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path.name} line {n} is not KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if any(word in key for word in FORBIDDEN_ENV):
            raise ValueError(f"{path.name} contains {key}; broker passwords/PINs/OTP seeds must not be stored. "
                             "Remove it: Kite login is done by you in the browser")
        if key not in ALLOWED_ENV:
            raise ValueError(f"{path.name} line {n}: unknown key {key}. Allowed keys: {', '.join(sorted(ALLOWED_ENV))}")
        env[key] = value.strip().strip('"').strip("'")
    return env


def redirect_url(env: dict) -> str:
    url = env.get("KITE_REDIRECT_URL") or DEFAULT_REDIRECT
    u = urlsplit(url)
    local = u.hostname in ("127.0.0.1", "localhost")
    if u.scheme not in ("http", "https") or (u.scheme == "http" and not local) or not u.hostname:
        raise ValueError("KITE_REDIRECT_URL must be https, or http only on 127.0.0.1/localhost")
    if u.query or u.fragment or u.username or u.password:
        raise ValueError("KITE_REDIRECT_URL must not contain a query, fragment or credentials")
    return url


def callback_path(env: dict) -> str:
    return urlsplit(redirect_url(env)).path or "/"


def login_url(api_key: str, state: str) -> str:
    if not api_key.strip():
        raise ValueError("KITE_API_KEY is missing from the private env file")
    return LOGIN_HOST + "?" + urlencode({"v": 3, "api_key": api_key, "redirect_params": urlencode({"state": state})})


def _digest(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


class StateBook:
    """Pending login states. In memory (terminal) or persisted as hashes (server, survives restarts)."""

    def __init__(self, path: Path | None = None):
        self.path, self._lock, self._mem = path, threading.Lock(), {}

    def _load(self):
        if self.path is None:
            return dict(self._mem)
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (ValueError, OSError):
            return {}

    def _save(self, book):
        if self.path is None:
            self._mem = book
        else:
            atomic_json(self.path, book)

    def issue(self, at=None) -> str:
        at = timestamp(at) if at else now()
        state = secrets.token_urlsafe(32)
        with self._lock:
            book = {k: v for k, v in self._load().items() if timestamp(v) > at}
            if len(book) >= MAX_PENDING:  # keep the newest few; older pending logins become invalid
                for k in sorted(book, key=lambda k: book[k])[:len(book) - MAX_PENDING + 1]:
                    del book[k]
            book[_digest(state)] = (at + STATE_TTL).isoformat()
            self._save(book)
        return state

    def consume(self, state: str, at=None) -> bool:
        at = timestamp(at) if at else now()
        if not STATE.fullmatch(state or ""):
            return False
        with self._lock:
            book = self._load()
            expires = book.pop(_digest(state), None)
            self._save({k: v for k, v in book.items() if timestamp(v) > at})
        return expires is not None and timestamp(expires) > at


def check_redirect(target: str, expected_path: str, states: StateBook, at=None) -> str:
    """Validate a redirect target (path + query). Returns the request token or raises LoginRejected."""
    u = urlsplit(target)
    if u.path != expected_path:
        raise LoginRejected("LOGIN_WRONG_PATH")
    try:
        q = parse_qs(u.query, keep_blank_values=True, strict_parsing=False, max_num_fields=12)
    except ValueError:
        raise LoginRejected("LOGIN_MALFORMED") from None
    if any(len(v) != 1 for v in q.values()):
        raise LoginRejected("LOGIN_DUPLICATE_PARAMETER")
    one = {k: v[0] for k, v in q.items()}
    if one.get("status", "success") != "success":
        raise LoginRejected("LOGIN_NOT_SUCCESSFUL")
    if not REQUEST_TOKEN.fullmatch(one.get("request_token", "")):
        raise LoginRejected("LOGIN_TOKEN_MISSING")
    if not states.consume(one.get("state", ""), at):
        raise LoginRejected("LOGIN_STATE_INVALID_OR_EXPIRED")
    return one["request_token"]


def next_expiry(at: datetime) -> datetime:
    """Kite access tokens expire at the next 06:00 IST (they can be invalidated earlier)."""
    local = timestamp(at)
    six = datetime.combine(local.date(), time(6), IST)
    return six if local < six else six + timedelta(days=1)


def complete_login(root: Path, env: dict, request_token: str, *, kite_factory=KiteReadOnly, at=None) -> dict:
    """Exchange the request token server-side, verify the account and save only the access token."""
    api_key, secret, expected = env.get("KITE_API_KEY", ""), env.get("KITE_API_SECRET", ""), env.get("KITE_USER_ID", "")
    if not api_key or not secret or not expected:
        raise ValueError("KITE_API_KEY, KITE_API_SECRET and KITE_USER_ID must all be in the private env file")
    session = kite_factory(api_key).exchange_token(request_token, secret)
    access_token = session.get("access_token") if isinstance(session, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise KiteError("Token response was missing the access token")
    if session.get("user_id") != expected:
        raise KiteError("The account that logged in is not KITE_USER_ID from the private env file; session not saved")
    at = timestamp(at) if at else now()
    record = {"api_key": api_key, "access_token": access_token, "login_at": at.isoformat(),
              "expires_at": next_expiry(at).isoformat()}
    atomic_json(root / SESSION_FILE, record)
    return {"login_at": record["login_at"], "expires_at": record["expires_at"]}


def session_status(root: Path, at=None) -> dict:
    """Safe-to-display session state; never returns the token."""
    at = timestamp(at) if at else now()
    path = root / SESSION_FILE
    if not path.exists():
        return {"state": "AUTH_REQUIRED", "reason": "NO_SESSION"}
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
        expires = timestamp(s["expires_at"])
    except (ValueError, KeyError, OSError, TypeError):
        return {"state": "AUTH_REQUIRED", "reason": "SESSION_FILE_UNREADABLE"}
    if expires <= at:
        return {"state": "AUTH_REQUIRED", "reason": "SESSION_EXPIRED", "expired_at": expires.isoformat()}
    return {"state": "AUTHENTICATED", "expires_at": expires.isoformat(), "login_at": s.get("login_at")}
