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
                raw = response.read(MAX_RESPONSE + 1)
                encoding = response.headers.get("Content-Encoding", "")
        except HTTPError as e:
            if e.code in (401, 403):
                raise AuthenticationRequired("Kite authentication expired or permission denied; log in again") from None
            # Provider bodies and URLs can contain sensitive data; do not log them.
            raise KiteError(f"Kite HTTP {e.code}; no automatic retry") from None
        except (URLError, TimeoutError):
            raise KiteError("Kite connection failed; no automatic retry") from None
        if len(raw) > MAX_RESPONSE:
            raise KiteError("Provider response exceeded the configured limit")
        if encoding.lower() == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
                raw = zipped.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise KiteError("Decompressed provider response exceeded the configured limit")
        if path.startswith("/instruments/") and not HISTORY.fullmatch(path):
            return raw.decode("utf-8-sig")
        try:
            body = json.loads(raw)
            if body.get("status") != "success":
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
