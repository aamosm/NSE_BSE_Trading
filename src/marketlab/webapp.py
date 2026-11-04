"""Private phone app server (installable PWA) and official Kite login callback.

Bound to 127.0.0.1 only. On the server, Tailscale Serve provides HTTPS on the private tailnet and
forwards here; nothing is exposed publicly. Optionally every route except /health requires the
Tailscale identity header to equal MARKETLAB_TAILNET_USER.

Routes are an allowlist. The only state-changing routes are the analysis pause/resume controls (CSRF:
custom header required, so cross-site pages cannot send them) and the login callback. There is no
order, transfer or broker-write endpoint. Request lines are never logged (the callback query carries
the request token); every dynamic or authentication response is ``Cache-Control: no-store``.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import account, login, service, webassets
from .common import now, timestamp
from .kite import KiteError
from .store import Store

STATIC = {
    "/": ("text/html; charset=utf-8", webassets.INDEX_HTML),
    "/app.js": ("text/javascript; charset=utf-8", webassets.APP_JS),
    "/app.css": ("text/css; charset=utf-8", webassets.APP_CSS),
    "/sw.js": ("text/javascript; charset=utf-8", webassets.SERVICE_WORKER),
    "/manifest.webmanifest": ("application/manifest+json", webassets.MANIFEST),
    "/icon.svg": ("image/svg+xml", webassets.ICON_SVG),
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
QUOTA = 256 * 1024 * 1024
BLOCKERS = [
    ("NO_VALIDATED_MODEL", "No forecasting model has passed validation; every decision is WAIT."),
    ("PAPER_LEDGER_NOT_BUILT", "The simulated cash ledger is not built yet (milestone F)."),
    ("BSE_CALENDAR_UNVERIFIED", "BSE trading calendar not verified; BSE simulations are blocked."),
    ("CALENDAR_2027_MISSING", "2027 NSE calendar not published/loaded; dates after 31 Dec 2026 are blocked."),
    ("MIS_LIST_UNAVAILABLE", "Broker intraday eligibility list unavailable; the intraday sleeve is blocked."),
    ("CONTRACT_NOTE_UNRECONCILED", "STT/stamp aggregation not yet reconciled with a real contract note."),
    ("PRICE_HISTORY_SHORT", "Exchange price history collected only from 30 Oct 2026; Kite history is adjusted."),
]


def _age_seconds(t, at):
    return None if t is None else max(0, int((at - t).total_seconds()))


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(path) if path.exists() else []:
        for f in files:
            try:
                total += (Path(dirpath) / f).stat().st_size
            except OSError:
                pass
    return total


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    return str(x)  # Decimal -> exact string


def upcoming(market: Path, at: datetime, days=14) -> dict:
    from . import master, sources
    out = {"corporate_actions": [], "new_listings": [], "source": {}}
    found = sources.latest_vintage(market, "nse_rss_corporate_actions", at)
    if found:
        import xml.etree.ElementTree as ET
        raw = sources.read_raw(market, "nse_rss_corporate_actions", found[0])
        if raw and b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper():
            for item in ET.fromstring(raw).findall(".//item"):
                title = (item.findtext("title") or "").strip()
                name, _, rest = title.partition(" - Ex-Date:")
                try:
                    ex = datetime.strptime(rest.strip()[:11], "%d-%b-%Y").date()
                except ValueError:
                    continue
                if at.date() <= ex <= at.date() + timedelta(days=days):
                    purpose = (item.findtext("description") or "").split("PURPOSE:")[-1].split("|")[0].strip()
                    out["corporate_actions"].append({"company": name.strip()[:120], "ex_date": ex.isoformat(),
                                                     "purpose": purpose[:160]})
        out["source"]["corporate_actions"] = found[0].isoformat()
    found = sources.latest_vintage(market, "nse_equity_list", at)
    if found:
        raw = sources.read_raw(market, "nse_equity_list", found[0])
        for r in master.parse_equity_list(raw) if raw else []:
            if r["listing_date"] and abs((r["listing_date"] - at.date()).days) <= days:
                out["new_listings"].append({"symbol": r["symbol"], "name": r["name"][:120],
                                            "listing_date": r["listing_date"].isoformat(), "series": r["series"]})
        out["source"]["new_listings"] = found[0].isoformat()
    out["corporate_actions"].sort(key=lambda r: r["ex_date"])
    out["new_listings"].sort(key=lambda r: r["listing_date"], reverse=True)
    return out


def status(root: Path, market: Path, at=None) -> dict:
    """Everything the phone shows. Actual account and simulated figures are separate top-level keys."""
    at = timestamp(at) if at else now()
    st = service.read_json(root / service.STATE_FILE, {})
    session = login.session_status(root, at)
    evidence = root / "evidence.sqlite3"
    actual, decisions = {"batch": None, "sections": {}}, []
    if evidence.exists():
        db = Store(evidence)
        try:
            actual = account.account_view(db, at)
            decisions = [d["payload"] | {"recorded_at": d["received_at"]} for d in db.recent("paper_decision", 30)]
            ev_size = db.size_bytes()
        finally:
            db.close()
    else:
        ev_size = 0
    ages = {}
    catalog = market / "catalog.sqlite3"
    if catalog.exists():
        from . import sources
        db = sources.catalog(market)
        try:
            for source, t in db.latest_by_source("source_file").items():
                ages[source.removeprefix("public:")] = {"received_at": t.isoformat(), "age_seconds": _age_seconds(t, at)}
        finally:
            db.close()
    finished = (actual.get("batch") or {}).get("finished_at")
    blockers = [{"code": c, "text": t} for c, t in BLOCKERS]
    if session["state"] != "AUTHENTICATED" or st.get("auth_invalid"):
        blockers.insert(0, {"code": "AUTH_REQUIRED", "text": "Kite login needed for broker data today."})
    for provider, b in (st.get("breakers") or {}).items():
        blockers.insert(0, {"code": "SOURCE_FAILING", "text": f"{provider} failing; retry after {b.get('open_until')}."})
    try:
        events = upcoming(market, at)
    except (OSError, ValueError) as e:
        events = {"corporate_actions": [], "new_listings": [], "error": type(e).__name__}
    return _jsonable({
        "at": at,
        "live_orders": False,
        "service": {"state": st.get("state", "NOT_STARTED"), "analysis": st.get("analysis", "ACTIVE"),
                    "updated_at": st.get("updated_at"), "jobs": st.get("jobs", {}),
                    "heartbeat": st.get("heartbeat"), "last_alert": st.get("last_alert")},
        "session": {k: v for k, v in session.items() if k in ("state", "reason", "expires_at")}
                   | ({"invalidated": True} if st.get("auth_invalid") else {}),
        "data": {"broker_last_batch_at": finished,
                 "broker_age_seconds": _age_seconds(timestamp(finished), at) if finished else None,
                 "sources": ages},
        "actual": actual,
        "simulated": {"kind": "SIMULATED_PAPER", "starting_cash": "10000.00", "cash": "10000.00", "positions": [],
                      "pnl": "0.00", "state": "PAPER_LEDGER_NOT_BUILT",
                      "note": "No simulated trade has been made. These figures are not your real account."},
        "decisions": decisions,
        "events": events,
        "blockers": blockers,
        "research_queue": [],
        "budget": {"evidence_bytes": ev_size, "evidence_quota_bytes": QUOTA,
                   "market_files_bytes": _dir_size(market / "raw"),
                   "catalog_bytes": catalog.stat().st_size if catalog.exists() else 0,
                   "recurring": [{"item": "Kite Connect data plan", "cost": "Rs 500/month", "state": "paid by owner"},
                                 {"item": "Server (DigitalOcean Basic 1 vCPU / 2 GiB)", "cost": "US$12/month + tax",
                                  "state": "not provisioned"},
                                 {"item": "Tailscale Personal", "cost": "free", "state": "not installed"},
                                 {"item": "Runtime LLM calls", "cost": "0", "state": "none configured"}]},
    })


class App:
    def __init__(self, root: Path, market: Path):
        self.root, self.market = root, market
        self.states = login.StateBook(root / login.STATE_FILE)

    def env(self):
        return login.load_env(self.root)

    def callback_path(self):
        return login.callback_path(self.env())


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        timeout = 15
        server_version = "MarketLab"
        sys_version = ""

        def log_message(self, *_):
            pass  # never log request lines: the login callback query carries the request token

        def _send(self, code, body: bytes, ctype, cache="no-store", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, value):
            self._send(code, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _page(self, code, title, text, link=("/", "Back to the app")):
            body = webassets.message_page(title, text, link)
            self._send(code, body.encode(), "text/html; charset=utf-8")

        def _allowed(self):
            want = app.env().get("MARKETLAB_TAILNET_USER")
            return not want or self.headers.get("Tailscale-User-Login", "") == want

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                return self._json(200, {"service": "up", "live_orders": False})
            if not self._allowed():
                return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            try:
                cb = app.callback_path()
            except ValueError:
                cb = None
            if cb and path == cb and "request_token=" in self.path:
                return self._callback()
            if path in STATIC:
                ctype, body = STATIC[path]
                return self._send(200, body.encode(), ctype, cache="no-cache")
            if path in ("/icon-192.png", "/icon-512.png"):
                return self._send(200, webassets.icon_png(192 if "192" in path else 512), "image/png", cache="no-cache")
            if path == "/api/status":
                return self._json(200, status(app.root, app.market))
            if path == "/login/start":
                return self._login_start()
            return self._send(404, b"Not found", "text/plain; charset=utf-8")

        def _login_start(self):
            env = app.env()
            try:
                login.redirect_url(env)
                url = login.login_url(env.get("KITE_API_KEY", ""), app.states.issue())
            except ValueError as e:
                return self._page(500, "Login not configured", str(e))
            self._send(302, b"", "text/plain; charset=utf-8", extra={"Location": url})

        def _callback(self):
            try:
                token = login.check_redirect(self.path, app.callback_path(), app.states)
                saved = login.complete_login(app.root, app.env(), token)
            except login.LoginRejected as e:
                return self._page(400, "Login not accepted", f"Reason: {e}. Start the login again from the app.")
            except (KiteError, ValueError) as e:
                return self._page(502, "Login failed", f"{type(e).__name__}: {e}")
            return self._page(200, "Kite login complete",
                              f"Session saved on the server; it expires {saved['expires_at']}. Collection resumes "
                              "automatically within a minute. No order capability exists in this app.")

        def do_POST(self):
            path = urlsplit(self.path).path
            if not self._allowed():
                return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            if path not in ("/api/analysis/pause", "/api/analysis/resume"):
                return self._send(405, b"This service has no order or write endpoints.", "text/plain; charset=utf-8")
            if self.headers.get("X-MarketLab-Action") != "1":
                return self._send(403, b"Missing action header", "text/plain; charset=utf-8")
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1024:
                return self._send(413, b"Too large", "text/plain; charset=utf-8")
            self.rfile.read(length)
            return self._json(200, service.set_paused(app.root, path.endswith("/pause")))

        def _refuse(self):
            self._send(405, b"Method not allowed", "text/plain; charset=utf-8")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    return Handler


def serve(root: Path, market: Path, port=8765, host="127.0.0.1"):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("The app binds to loopback only; use Tailscale Serve for private HTTPS")
    ThreadingHTTPServer((host, port), make_handler(App(root, market))).serve_forever()
