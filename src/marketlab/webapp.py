"""Private dashboard server (installable PWA) and official Kite login callback.

Bound to 127.0.0.1 only. On a server, Tailscale Serve provides HTTPS on the private tailnet and forwards here;
nothing is exposed publicly. Optionally every route except /health requires the Tailscale identity header to
equal MARKETLAB_TAILNET_USER.

Routes are an allowlist. State-changing routes (all POST, all requiring the X-MarketLab-Action header so that
cross-site pages cannot send them): analysis pause/resume, policy edits (validated, bounded) and job requests for
the scheduler. There is no order, transfer or broker-write endpoint. Request lines are never logged (the login
callback query carries the request token); every dynamic or authentication response is ``Cache-Control: no-store``.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
RUNS = Path("data/runs")
BLOCKERS = [
    ("NO_PROMOTED_MODEL", "No candidate has passed the promotion rule (spec 8.6); every decision is WAIT."),
    ("PRICE_HISTORY_SHORT", "Exchange price history held only from 30 Oct 2026; the backfill (2016 onward) is pending."),
    ("CORPORATE_ACTIONS_UNVERIFIED", "Exchange-implied factors are used; hypothesis H-CA1 (dividends) is unverified."),
    ("PAPER_LEDGER_NOT_BUILT", "The simulated cash ledger with reservations is not built yet."),
    ("BSE_CALENDAR_UNVERIFIED", "BSE trading calendar not verified; BSE simulations are blocked."),
    ("MIS_LIST_UNAVAILABLE", "Broker intraday eligibility list unavailable; no intraday candidate exists."),
    ("CONTRACT_NOTE_UNRECONCILED", "STT/stamp aggregation not yet reconciled with a real contract note."),
]
MAX_BODY = 8192


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
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if x is None or isinstance(x, (bool, int, str)):
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
                    out["corporate_actions"].append({"company": name.strip()[:120], "ex_date": ex.isoformat(), "purpose": purpose[:160]})
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


def _latest_file(folder: Path, suffix=".json"):
    if not folder.exists():
        return None
    files = sorted(p for p in folder.glob("*" + suffix) if p.is_file())
    return files[-1] if files else None


def status(root: Path, market: Path, at=None) -> dict:
    """Overview: actual account and simulated figures are separate top-level keys."""
    at = timestamp(at) if at else now()
    st = service.read_json(root / service.STATE_FILE, {})
    session = login.session_status(root, at)
    evidence = root / "evidence.sqlite3"
    actual, decisions = {"batch": None, "sections": {}}, []
    ev_size = 0
    if evidence.exists():
        db = Store(evidence)
        try:
            actual = account.account_view(db, at)
            decisions = [d["payload"] | {"recorded_at": d["received_at"]} for d in db.recent("paper_decision", 30)]
            ev_size = db.size_bytes()
        finally:
            db.close()
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
    updated = st.get("updated_at")
    latest_decision = _latest_file(RUNS / "decisions")
    decision_summary = None
    if latest_decision:
        try:
            d = json.loads(latest_decision.read_text(encoding="utf-8"))
            decision_summary = {k: d.get(k) for k in ("day", "action", "reasons", "candidate", "h", "generated_at")}
            decision_summary["forecasts"] = len(d.get("forecasts", []))
            decision_summary["plan"] = (d.get("plan") or {}).get("quantities", {})
        except (ValueError, OSError):
            decision_summary = {"error": "unreadable"}
    return _jsonable({
        "at": at, "live_orders": False,
        "service": {"state": st.get("state", "NOT_STARTED"), "analysis": st.get("analysis", "ACTIVE"), "updated_at": updated,
                    "scheduler_age_seconds": _age_seconds(timestamp(updated), at) if updated else None,
                    "jobs": st.get("jobs", {}), "heartbeat": st.get("heartbeat"), "last_alert": st.get("last_alert"),
                    "last_gap": st.get("last_gap"), "calendar": st.get("calendar"), "breakers": st.get("breakers", {})},
        "session": {k: v for k, v in session.items() if k in ("state", "reason", "expires_at")} | ({"invalidated": True} if st.get("auth_invalid") else {}),
        "data": {"broker_last_batch_at": finished, "broker_age_seconds": _age_seconds(timestamp(finished), at) if finished else None,
                 "sources": ages},
        "actual": actual,
        "simulated": {"kind": "SIMULATED_PAPER", "starting_cash": "10000.00", "cash": "10000.00", "positions": [], "pnl": "0.00",
                      "state": "PAPER_LEDGER_NOT_BUILT", "note": "No simulated trade has been made. These figures are not your real account."},
        "decisions": decisions, "latest_decision": decision_summary, "events": events, "blockers": blockers,
        "policy": service.policy(root),
        "budget": {"evidence_bytes": ev_size, "evidence_quota_bytes": QUOTA, "market_files_bytes": _dir_size(market / "raw"),
                   "catalog_bytes": catalog.stat().st_size if catalog.exists() else 0,
                   "panel_bytes": (market / "panel.sqlite3").stat().st_size if (market / "panel.sqlite3").exists() else 0,
                   "recurring": [{"item": "Kite Connect data plan", "cost": "Rs 500/month", "state": "paid by owner"},
                                 {"item": "Server (optional)", "cost": "US$12/month + tax", "state": "not provisioned"},
                                 {"item": "Research provider", "cost": "0", "state": "none configured"}]},
    })


def data_coverage(market: Path, calendar=None) -> dict:
    """Per-source stored dates, panel sessions, master snapshots, missing trading days in the last 30 days."""
    from . import sources
    out = {"sources": {}, "panel": None, "master": [], "missing_recent": {}}
    catalog = market / "catalog.sqlite3"
    if catalog.exists():
        db = sources.catalog(market)
        try:
            rows = db.db.execute("SELECT source, subject, payload FROM observations WHERE kind='source_file'").fetchall()
        finally:
            db.close()
        for source, subject, payload in rows:
            p = json.loads(payload)
            name = source.removeprefix("public:")
            s = out["sources"].setdefault(name, {"stored": [], "not_published": [], "failed": []})
            key = {"STORED": "stored", "NOT_PUBLISHED": "not_published"}.get(p.get("result"), "failed")
            if subject not in s[key]:
                s[key].append(subject)
        for s in out["sources"].values():
            for k in s:
                s[k].sort()
            s["count"] = len(s["stored"])
            s["first"], s["last"] = (s["stored"][0], s["stored"][-1]) if s["stored"] else (None, None)
    panel_path = market / "panel.sqlite3"
    if panel_path.exists():
        from .quant.panel import Panel
        pn = Panel(panel_path)
        try:
            sess = pn.sessions()
            nf = pn.db.execute("SELECT count(*) FROM implied_factors").fetchone()[0]
            out["panel"] = {"sessions": len(sess), "first": sess[0].isoformat() if sess else None,
                            "last": sess[-1].isoformat() if sess else None, "isins": len(pn.isins()), "implied_factors": nf}
        finally:
            pn.close()
    master_path = market / "master.sqlite3"
    if master_path.exists():
        import sqlite3
        con = sqlite3.connect(master_path)
        try:
            out["master"] = [r[0] for r in con.execute("SELECT DISTINCT snapshot_date FROM listings ORDER BY snapshot_date DESC LIMIT 30")]
        finally:
            con.close()
    try:
        cal = calendar or sources.load_calendar(market)[0]
        from .rules.types import Exchange
        today = now().date()
        days = [today - timedelta(days=i) for i in range(1, 31)]
        trading = [d.isoformat() for d in days if cal.is_trading_day(Exchange.NSE, d)]
        for name, spec in sources.BY_ID.items():
            if spec.dated and name in out["sources"]:
                have = set(out["sources"][name]["stored"])
                out["missing_recent"][name] = [d for d in trading if d not in have]
    except Exception as e:  # calendar unknown for a year: report, never guess
        out["missing_recent_error"] = type(e).__name__
    return out


def universe_view(market: Path, day: date | None = None) -> dict:
    panel_path = market / "panel.sqlite3"
    if not panel_path.exists():
        return {"error": "PANEL_NOT_BUILT"}
    from . import sources
    from .quant.panel import Panel
    from .quant.universe import ScreenPolicy, rule_inputs_for, screen
    pol = service.policy(Path("data/private"))
    pn = Panel(panel_path)
    try:
        sessions = pn.sessions()
        if not sessions:
            return {"error": "PANEL_EMPTY"}
        day = day or sessions[-1]
        cal = sources.load_calendar(market)[0]
        s = screen(pn, day, ScreenPolicy(v_min=pol["v_min_crore"] * 1e7, W=pol["capital"]), rule_inputs_for(market, day, cal), sessions)
        rows = []
        if s.isins:
            xs = {isin: b for isin, b in pn.cross_section(day)}
            for isin in s.isins[:300]:
                b = xs.get(isin)
                if b:
                    rows.append({"isin": isin, "symbol": b.symbol, "close": b.close, "value_crore": round(b.value / 1e7, 2)})
    finally:
        pn.close()
    return _jsonable({"day": day.isoformat(), "kept": len(s.isins), "unverified": s.unverified, "stats": s.stats, "rows": rows,
                      "policy": {"v_min_crore": pol["v_min_crore"], "capital": pol["capital"]}})


def evaluation_view(trial: str | None = None) -> dict:
    folder = RUNS / "eval"
    if not folder.exists():
        return {"reports": []}
    if trial:
        safe = "".join(ch for ch in trial if ch.isalnum() or ch in ".-_")
        p = folder / (safe + ".json")
        if not p.exists():
            return {"error": "NOT_FOUND"}
        rep = json.loads(p.read_text(encoding="utf-8"))
        for f in rep.get("folds", []):
            sim = f.get("simulation") or {}
            if "trades" in sim:
                sim["trades"] = sim["trades"][-200:]
        return rep
    reports = []
    for p in sorted(folder.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        reports.append({k: r.get(k) for k in ("trial_id", "generated_at", "folds_done", "n_trades", "net_rupees_total",
                                              "folds_positive", "coverage_80_mean", "brier_skill_mean", "rows", "sessions")}
                       | {"sharpe_per_trade": (r.get("pooled") or {}).get("sharpe_per_trade"), "config": r.get("config")})
    return {"reports": reports}


def decision_view() -> dict:
    p = _latest_file(RUNS / "decisions")
    if not p:
        return {"decision": None, "available": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"decision": None, "error": "unreadable"}
    return {"decision": d, "available": [q.name for q in sorted((RUNS / "decisions").glob("*.json"))][-30:]}


def research_view(root: Path, market: Path) -> dict:
    from .researcher import commands as rc, jobs
    out = {"provider": "none", "queue": {}, "usage": None}
    try:
        out["usage"] = rc.usage(root, market)
        out["provider"] = out["usage"].get("provider", "none")
    except Exception as e:
        out["usage_error"] = type(e).__name__
    qp = rc.paths(market)["queue"]
    if qp.exists():
        q = jobs.Queue(qp)
        try:
            counts = {}
            for (jid,) in q.db.execute("SELECT job_id FROM jobs"):
                st, _ = q.state(jid)
                counts[st or "NEW"] = counts.get(st or "NEW", 0) + 1
            out["queue"] = counts
        finally:
            q.close()
    return out


def requests_view(root: Path) -> dict:
    return {"requests": service.list_requests(root)}


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
            self._send(code, webassets.message_page(title, text, link).encode(), "text/html; charset=utf-8")

        def _allowed(self):
            want = app.env().get("MARKETLAB_TAILNET_USER")
            return not want or self.headers.get("Tailscale-User-Login", "") == want

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlsplit(self.path)
            path, q = u.path, parse_qs(u.query)
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
            try:
                if path == "/api/status":
                    return self._json(200, status(app.root, app.market))
                if path == "/api/data":
                    return self._json(200, _jsonable(data_coverage(app.market)))
                if path == "/api/universe":
                    d = q.get("date", [None])[0]
                    return self._json(200, universe_view(app.market, date.fromisoformat(d) if d else None))
                if path == "/api/evaluation":
                    return self._json(200, _jsonable(evaluation_view(q.get("trial", [None])[0])))
                if path == "/api/decision":
                    return self._json(200, _jsonable(decision_view()))
                if path == "/api/research":
                    return self._json(200, _jsonable(research_view(app.root, app.market)))
                if path == "/api/requests":
                    return self._json(200, _jsonable(requests_view(app.root)))
                if path == "/api/config":
                    return self._json(200, {"policy": service.policy(app.root), "bounds": service.POLICY_BOUNDS,
                                            "request_kinds": sorted(service.REQUEST_KINDS)})
            except (OSError, ValueError, KeyError) as e:
                return self._json(500, {"error": type(e).__name__})
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
            return self._page(200, "Kite login complete", f"Session saved; it expires {saved['expires_at']}. Collection resumes "
                              "automatically within a minute. No order capability exists in this app.")

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return None
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                body = json.loads(raw)
            except ValueError:
                return None
            return body if isinstance(body, dict) else None

        def do_POST(self):
            path = urlsplit(self.path).path
            if not self._allowed():
                return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            if path not in ("/api/analysis/pause", "/api/analysis/resume", "/api/config", "/api/request"):
                return self._send(405, b"This service has no order or write endpoints.", "text/plain; charset=utf-8")
            if self.headers.get("X-MarketLab-Action") != "1":
                return self._send(403, b"Missing action header", "text/plain; charset=utf-8")
            body = self._read_body()
            if body is None:
                return self._json(400, {"error": "BAD_BODY"})
            if path.startswith("/api/analysis/"):
                return self._json(200, service.set_paused(app.root, path.endswith("/pause")))
            try:
                if path == "/api/config":
                    return self._json(200, {"policy": service.set_policy(app.root, body)})
                return self._json(200, service.submit_request(app.root, str(body.get("kind", "")), body.get("args") or {}))
            except ValueError as e:
                return self._json(400, {"error": str(e)[:200]})

        def _refuse(self):
            self._send(405, b"Method not allowed", "text/plain; charset=utf-8")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    return Handler


def serve(root: Path, market: Path, port=8765, host="127.0.0.1"):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("The app binds to loopback only; use Tailscale Serve for private HTTPS")
    ThreadingHTTPServer((host, port), make_handler(App(root, market))).serve_forever()
