"""Narrow read-only REST adapter. The sole POST is the login token exchange."""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import netutil  # neutral helpers; the research provider uses netutil, never this module

READ_PATHS = frozenset({
    "/user/profile", "/user/margins/equity", "/portfolio/holdings",
    "/portfolio/positions", "/orders", "/trades", "/instruments/NSE",
    "/instruments/BSE", "/quote", "/quote/ohlc", "/quote/ltp",
})
HISTORY = re.compile(r"/instruments/historical/[1-9][0-9]*/(day|minute|3minute|5minute|10minute|15minute|30minute|60minute)")
MAX_RESPONSE = 32 * 1024 * 1024


class KiteError(RuntimeError):
    pass


class AuthenticationRequired(KiteError):
    pass


class ReadOnlyViolation(KiteError):
    pass


class PermissionDenied(KiteError):
    """Kite refused an endpoint for this app/account (e.g. quotes or history without the paid data plan)."""


# Kite's documented error_type values (https://kite.trade/docs/connect/v3/exceptions/, checked 5 Nov 2026)
# plus PermissionException, which the official client library defines and Kite returns for endpoints
# outside the app's plan. Any other value is reported as UnknownErrorType: provider text is never echoed.
KITE_ERROR_TYPES = frozenset({
    "TokenException", "UserException", "OrderException", "InputException", "MarginException",
    "HoldingException", "NetworkException", "DataException", "GeneralException", "PermissionException",
})
READ_DEADLINE = 90.0  # seconds for one complete response, however slowly it trickles in


def _error_type(e: HTTPError) -> str:
    """Kite's enumerated error_type (e.g. TokenException). Never the message or any other body field."""
    try:
        body = json.loads(e.read(65536) or b"{}")
    except Exception:
        return ""
    kind = body.get("error_type", "") if isinstance(body, dict) else ""
    if kind in ("", None):
        return ""
    return kind if isinstance(kind, str) and kind in KITE_ERROR_TYPES else "UnknownErrorType"


def read_bounded(response, limit=MAX_RESPONSE, deadline=READ_DEADLINE, clock=time.monotonic):
    """Read a whole response under a size limit and a total deadline (socket timeouts are per read)."""
    try:
        return netutil.read_bounded(response, limit, deadline, clock)
    except netutil.ResponseLimit as e:
        raise KiteError(str(e).replace("Response exceeded", "Kite response exceeded")) from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise KiteError("Unexpected provider redirect refused")



def guard(method: str, path: str) -> None:
    if method == "POST" and path == "/session/token":
        return
    if method == "GET" and (path in READ_PATHS or HISTORY.fullmatch(path)):
        return
    raise ReadOnlyViolation("This application permits data reads and token exchange only")


class KiteReadOnly:
    def __init__(self, api_key: str, access_token: str = "", *, transport=None):
        if not api_key.strip():
            raise ValueError("API key is missing")
        self.api_key = api_key
        self.access_token = access_token
        self._transport = transport or self._http
        self._last_call = 0.0

    def _http(self, method, path, params):
        guard(method, path)
        # One request/second across endpoints is below the published REST limits.
        time.sleep(max(0, 1.05 - (time.monotonic() - self._last_call)))
        self._last_call = time.monotonic()
        encoded = urlencode(params or {}, doseq=True).encode()
        url = "https://api.kite.trade" + path
        headers = {"X-Kite-Version": "3", "User-Agent": "MarketLab-ReadOnly/0.2"}
        if method == "GET":
            if not self.access_token:
                raise AuthenticationRequired("Log in again using the auth command")
            headers["Authorization"] = f"token {self.api_key}:{self.access_token}"
            url += ("?" + encoded.decode()) if encoded else ""
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = Request(url, data=encoded if method == "POST" else None, headers=headers, method=method)
        try:
            with build_opener(NoRedirect()).open(req, timeout=20) as response:
                raw = read_bounded(response)
                encoding = response.headers.get("Content-Encoding", "")
        except HTTPError as e:
            # Provider bodies and URLs can contain sensitive data; only the enumerated error type is used.
            kind = _error_type(e)
            if kind == "TokenException" or e.code == 401:
                raise AuthenticationRequired("Kite session expired or invalid (TokenException); run auth again") from None
            if kind == "PermissionException":
                raise PermissionDenied("Kite refused this endpoint (PermissionException); your Kite app plan "
                                       "may not include it") from None
            if e.code == 403:
                raise AuthenticationRequired("Kite returned HTTP 403; the session expired or access was denied") from None
            if kind == "InputException" and path == "/session/token":
                raise KiteError("Kite rejected the login exchange (InputException): the request token may have "
                                "expired (it lasts a few minutes) or the API secret is wrong") from None
            label = f" ({kind})" if kind else ""
            raise KiteError(f"Kite HTTP {e.code}{label}; no automatic retry") from None
        except (URLError, TimeoutError):
            raise KiteError("Kite connection failed; no automatic retry") from None
        if encoding.lower() == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
                raw = zipped.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise KiteError("Decompressed provider response exceeded the configured limit")
        if path.startswith("/instruments/") and not HISTORY.fullmatch(path):
            return raw.decode("utf-8-sig")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or body.get("status") != "success":
                raise KiteError("Kite returned an unsuccessful response")
            return body["data"]
        except (ValueError, KeyError, TypeError):
            raise KiteError("Unexpected Kite response schema") from None

    def _request(self, method, path, params=None):
        guard(method, path)
        return self._transport(method, path, params)

    def get(self, path, params=None):
        return self._request("GET", path, params)

    def exchange_token(self, request_token: str, api_secret: str):
        if not request_token or not api_secret:
            raise ValueError("Request token and secret are required")
        digest = hashlib.sha256((self.api_key + request_token + api_secret).encode()).hexdigest()
        return self._request("POST", "/session/token", {
            "api_key": self.api_key, "request_token": request_token, "checksum": digest,
        })

    def quotes(self, instruments):
        if not 1 <= len(instruments) <= 100:
            raise ValueError("Use 1 to 100 exchange:symbol entries")
        if any(not re.fullmatch(r"(NSE|BSE):[A-Za-z0-9&_.-]+", x) for x in instruments):
            raise ValueError("Only explicit NSE/BSE symbols are supported")
        return self.get("/quote", {"i": instruments})

    def history(self, token: int, interval: str, start, end):
        return self.get(f"/instruments/historical/{token}/{interval}", {
            "from": start, "to": end, "continuous": 0, "oi": 0,
        })
