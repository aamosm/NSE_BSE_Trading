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
from datetime import date, datetime, time as clock, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import account, buildinfo, decisions, login, service, webassets
from .common import IST, now, timestamp
from .rules.types import RuleUnknown as RuleUnknownError
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
RUNS: Path | None = None  # None: runs live beside the private folder (decisions.runs_dir); tests may override
# Known limitations that no data in this process can clear (each is listed with basis KNOWN_LIMITATION).
KNOWN_LIMITATIONS = [
    ("CORPORATE_ACTIONS_UNVERIFIED", "Exchange-implied factors are unverified against an action history; hypothesis "
                                     "H-CA1 (dividends) is open, so windows with unlisted factors are excluded."),
    ("BSE_CALENDAR_UNVERIFIED", "BSE trading calendar not verified; BSE simulations are blocked."),
    ("MIS_LIST_UNAVAILABLE", "Broker intraday eligibility list unavailable; no intraday candidate exists."),
    ("CONTRACT_NOTE_UNRECONCILED", "STT/stamp aggregation not yet reconciled with a real contract note."),
]
FIRST_FOLD_SESSIONS = 750 + 125 + 250  # training + one test fold + the locked holdout (spec 8.1-8.2)
SCHEDULER_INTERVAL = 60  # seconds, unless the scheduler state records its own interval
MAX_BODY = 8192


def _runs(root: Path) -> Path:
    return RUNS if RUNS is not None else decisions.runs_dir(root)


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


def listing_route(series: str, name: str) -> str:
    """What the equity list can and cannot say about how a security arrived."""
    s, n = (series or "").upper(), (name or "").upper()
    if s == "RE" or "RIGHTS" in n:
        return "RIGHTS_ENTITLEMENT"
    if s in ("SM", "ST", "SZ"):
        return "SME_SEGMENT"
    return "ROUTE_UNVERIFIED"  # IPO, migration, relisting or cross-listing cannot be told apart from this file


def upcoming(market: Path, at: datetime, days=14) -> dict:
    """Calendar inputs only: ex-dates and listing dates are not signals or expected profit."""
    from . import master, sources
    out = {"corporate_actions": [], "listings_recent": [], "listings_upcoming": [], "source": {}}
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
            ld = r["listing_date"]
            if not ld or abs((ld - at.date()).days) > days:
                continue
            row = {"symbol": r["symbol"], "name": r["name"][:120], "listing_date": ld.isoformat(), "series": r["series"],
                   "route": listing_route(r["series"], r["name"])}
            out["listings_upcoming" if ld > at.date() else "listings_recent"].append(row)
        out["source"]["listings"] = found[0].isoformat()
    out["corporate_actions"].sort(key=lambda r: r["ex_date"])
    out["listings_recent"].sort(key=lambda r: r["listing_date"], reverse=True)
    out["listings_upcoming"].sort(key=lambda r: r["listing_date"])
    return out


def _latest_file(folder: Path, suffix=".json"):
    if not folder.exists():
        return None
    files = sorted(p for p in folder.glob("*" + suffix) if p.is_file())
    return files[-1] if files else None


def market_session(cal, at: datetime) -> dict:
    """The exchange session state now, from the loaded calendar; UNKNOWN when the year is not loaded."""
    from .rules.types import Exchange, RuleUnknown
    d, t = at.date(), at.time()
    try:
        if not cal.covers(Exchange.NSE, d):
            return {"status": "UNKNOWN_CALENDAR", "day": d.isoformat()}
        trading = cal.is_trading_day(Exchange.NSE, d)
        special = cal.is_special_session(Exchange.NSE, d)
        opens = cal.session_open(Exchange.NSE, d) if trading else None
    except RuleUnknown:
        return {"status": "SPECIAL_SESSION_TIMETABLE_UNKNOWN", "day": d.isoformat()}
    if not trading:
        return {"status": "NO_SESSION", "day": d.isoformat()}
    if special:
        return {"status": "SPECIAL_SESSION_DAY", "day": d.isoformat(), "opens": opens.isoformat()}
    state = "BEFORE_OPEN" if t < opens else "OPEN" if t < clock(15, 30) else "CLOSED"  # regular NSE timings
    return {"status": state, "day": d.isoformat(), "opens": opens.isoformat()}


def broker_expected(cal, at: datetime) -> bool | None:
    """Is a broker batch due now (the scheduler's read window)? None when the calendar cannot say."""
    trading = service._trading(cal, at.date())
    if trading is None:
        return None
    if not trading:
        return False
    try:
        opens = cal.session_open(service.Exchange.NSE, at.date())
    except service.RuleUnknown:
        return None
    return (datetime.combine(at.date(), opens, IST) - service.BROKER_LEAD).time() <= at.time() <= clock(16, 30)


def health(st: dict, session: dict, actual: dict, cal, at: datetime, promotion: tuple) -> dict:
    """Separate signals, each derived from timestamps now rather than from a saved state word."""
    updated = st.get("updated_at")
    interval = int(st.get("interval_seconds") or SCHEDULER_INTERVAL)
    age = _age_seconds(timestamp(updated), at) if updated else None
    if age is None:
        sched = "NEVER_STARTED"
    elif age <= 3 * interval:
        sched = "ALIVE"
    else:
        sched = "MISSED_HEARTBEATS"
    silence = age if (age is not None and age > service.GAP_THRESHOLD.total_seconds()) else None
    finished = (actual.get("batch") or {}).get("finished_at")
    b_age = _age_seconds(timestamp(finished), at) if finished else None
    expected = broker_expected(cal, at)
    auth_ok = session["state"] == "AUTHENTICATED" and not st.get("auth_invalid")
    if expected is None:
        broker = "UNKNOWN_CALENDAR"
    elif not expected:
        broker = "IDLE_BY_SCHEDULE"
    elif not auth_ok:
        broker = "AUTH_REQUIRED"
    elif b_age is None:
        broker = "NO_BATCH_YET"
    else:
        broker = "FRESH" if b_age <= 600 else "OVERDUE"
    usable, cash_reasons = account.fresh_for_cash_decision(actual, at) if actual.get("batch") else (False, ["NO_COMPLETED_BATCH"])
    record, problems = promotion
    paper_reasons = [] if record else ["MODEL_NOT_PROMOTED"]
    if sched != "ALIVE":
        paper_reasons.insert(0, "SCHEDULER_NOT_RUNNING")
    return {"web": "REACHABLE",
            "scheduler": {"status": sched, "last_seen": updated, "age_seconds": age, "interval_seconds": interval,
                          "reported_state": st.get("state"), "reported_state_current": sched == "ALIVE",
                          "current_silence_seconds": silence,
                          "last_recorded_gap": st.get("last_gap"),
                          "gap_note": "Gaps are recorded on the tick after a silence; a silence still in progress is "
                                      "current_silence_seconds."},
            "market": market_session(cal, at),
            "broker": {"status": broker, "expected_now": expected, "last_batch_at": finished, "age_seconds": b_age},
            "actual_cash_usable": {"ok": usable, "reasons": cash_reasons},
            "paper_decisions": {"eligible": not paper_reasons, "reasons": paper_reasons, "promotion_check": problems}}


def _paper_status(market: Path, calendar, root: Path, capital: float) -> dict:
    """The forward paper account rebuilt from recorded orders and stored files (quant.paper)."""
    from .quant import paper
    from .quant.panel import Panel
    panel_path = market / "panel.sqlite3"
    pn = Panel(panel_path) if panel_path.exists() else None
    try:
        return paper.status(pn, calendar, root, capital)
    except (ValueError, KeyError, RuleUnknownError) as e:
        return {"kind": "SIMULATED_PAPER", "state": "REBUILD_FAILED", "error": type(e).__name__, "configured_capital": capital,
                "cash": None, "positions": None, "pnl": None, "note": "The paper ledger could not be rebuilt; nothing is shown."}
    finally:
        if pn is not None:
            pn.close()


def status(root: Path, market: Path, at=None, calendar=None) -> dict:
    """Overview: actual account and simulated figures are separate top-level keys; health is derived now."""
    from . import sources
    from .quant import registry
    at = timestamp(at) if at else now()
    st = service.read_json(root / service.STATE_FILE, {})
    session = login.session_status(root, at)
    evidence = root / "evidence.sqlite3"
    actual = {"batch": None, "sections": {k: {"state": "MISSING"} for k in account.KINDS}}
    ev_size = 0
    if evidence.exists():
        db = Store(evidence)
        try:
            actual = account.account_view(db, at)
            ev_size = db.size_bytes()
        finally:
            db.close()
    timeline = decisions.timeline(root, 30)
    if calendar is None:
        calendar, cal_report = sources.load_calendar(market)
    else:
        cal_report = {"source": "SUPPLIED"}
    cal_report = dict(cal_report)
    cal_report["discrepancies_checked"] = cal_report.get("source") == "NSE_API"
    pol = service.policy(root)
    eff = service.effective_policy(root, pol)
    promotion = registry.verified_promotion(_runs(root), pol["candidate"], int(pol["h"]), eff.digest())
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
    hl = health(st, session, actual, calendar, at, promotion)
    blockers = []
    if hl["scheduler"]["status"] != "ALIVE":
        blockers.append({"code": "SCHEDULER_NOT_RUNNING", "basis": "DERIVED",
                         "text": "No scheduler tick in the last " + str(3 * hl["scheduler"]["interval_seconds"]) +
                                 " s; saved states and job results are as last reported."})
    if session["state"] != "AUTHENTICATED" or st.get("auth_invalid"):
        blockers.append({"code": "AUTH_REQUIRED", "basis": "DERIVED", "text": "Kite login needed for broker data today."})
    for provider, b in (st.get("breakers") or {}).items():
        blockers.append({"code": "SOURCE_FAILING", "basis": "LAST_REPORTED",
                         "text": f"{provider} failing; retry after {b.get('open_until')}."})
    if promotion[0] is None:
        blockers.append({"code": "NO_PROMOTED_MODEL", "basis": "DERIVED",
                         "text": f"No verified promotion record for candidate {pol['candidate']} at h = {pol['h']} under "
                                 "the effective policy; every decision is WAIT."})
    panel_sessions = None
    if (market / "panel.sqlite3").exists():
        import sqlite3
        con = sqlite3.connect(market / "panel.sqlite3")
        try:
            panel_sessions = con.execute("SELECT count(*) FROM sessions").fetchone()[0]
        except sqlite3.Error:
            panel_sessions = None
        finally:
            con.close()
    if not panel_sessions or panel_sessions < FIRST_FOLD_SESSIONS:
        blockers.append({"code": "PRICE_HISTORY_SHORT", "basis": "DERIVED",
                         "text": f"The price panel holds {panel_sessions or 0} sessions; a first development fold needs "
                                 f"{FIRST_FOLD_SESSIONS} exchange sessions plus 251 sessions of feature history."})
    blockers += [{"code": c, "basis": "KNOWN_LIMITATION", "text": t} for c, t in KNOWN_LIMITATIONS]
    try:
        events = upcoming(market, at)
    except (OSError, ValueError) as e:
        events = {"corporate_actions": [], "listings_recent": [], "listings_upcoming": [], "error": type(e).__name__}
    updated = st.get("updated_at")
    latest = decisions.latest(root, _runs(root))
    decision_summary = None
    if latest:
        decision_summary = {k: latest.get(k) for k in ("decision_id", "origin", "day", "action", "reasons", "candidate", "h",
                                                     "generated_at", "recorded_at", "integrity", "policy_digest",
                                                     "promotion_id", "forecasts", "plan_quantities", "diagnostic_artifact")}
        decision_summary["policy"] = latest.get("policy")
    return _jsonable({
        "at": at, "live_orders": False, "health": hl, "build": buildinfo.build_info(),
        "service": {"state": st.get("state", "NOT_STARTED"), "state_is_current": hl["scheduler"]["status"] == "ALIVE",
                    "analysis": st.get("analysis", "ACTIVE"), "updated_at": updated,
                    "scheduler_age_seconds": hl["scheduler"]["age_seconds"],
                    "jobs": st.get("jobs", {}), "heartbeat": st.get("heartbeat"), "last_alert": st.get("last_alert"),
                    "last_gap": st.get("last_gap"), "calendar": cal_report, "breakers": st.get("breakers", {})},
        "session": {k: v for k, v in session.items() if k in ("state", "reason", "expires_at")} | ({"invalidated": True} if st.get("auth_invalid") else {}),
        "data": {"broker_last_batch_at": finished, "broker_age_seconds": _age_seconds(timestamp(finished), at) if finished else None,
                 "sources": ages},
        "actual": actual,
        "simulated": _paper_status(market, calendar, root, pol["capital"]),
        "decisions": timeline, "latest_decision": decision_summary, "events": events, "blockers": blockers,
        "policy": pol, "policy_effective": eff.to_json(), "policy_digest": eff.digest(),
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


def universe_view(market: Path, day: date | None = None, root: Path | None = None) -> dict:
    panel_path = market / "panel.sqlite3"
    if not panel_path.exists():
        return {"error": "PANEL_NOT_BUILT"}
    from . import sources
    from .quant.panel import Panel
    from .quant.universe import ScreenPolicy, screen_for_day
    pol = service.policy(root or Path("data/private"))
    pn = Panel(panel_path)
    try:
        sessions = pn.sessions()
        if not sessions:
            return {"error": "PANEL_EMPTY"}
        day = day or sessions[-1]
        cal = sources.load_calendar(market)[0]
        s = screen_for_day(pn, day, ScreenPolicy(v_min=pol["v_min_crore"] * 1e7, W=pol["capital"]), market, cal)
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
                      "rule_inputs": s.availability, "note": "Rule files are those of the entry session (the next session).",
                      "policy": {"v_min_crore": pol["v_min_crore"], "capital": pol["capital"]}})


def _report_summary(r: dict, key: str, kind: str) -> dict:
    pr = r.get("promotion") or {}
    return {"key": key, "kind": kind, "trial_id": r.get("trial_id"), "run_id": r.get("run_id"),
            "generated_at": r.get("generated_at"), "folds_done": r.get("folds_done"), "n_trades": r.get("n_trades"),
            "net_rupees_total": r.get("net_rupees_total"), "folds_positive": r.get("folds_positive"),
            "verdict": pr.get("verdict"), "coverage_80": pr.get("coverage_80_pooled", r.get("coverage_80_mean")),
            "brier_skill": pr.get("brier_skill_pooled", r.get("brier_skill_mean")),
            "sharpe_per_trade": (r.get("pooled") or {}).get("sharpe_per_trade"), "sessions": r.get("sessions"),
            "data_end": r.get("data_end"), "manifest_hash": (r.get("manifest_hash") or "")[:12],
            "feature_builder": (r.get("candidate_spec") or {}).get("feature_builder")}


def evaluation_view(trial: str | None = None, root: Path | None = None) -> dict:
    """Immutable run reports: runs/eval/<trial>/<run>.json (development), runs/holdout/<trial>/<run>.json (the
    single holdout evaluation) and older flat files (legacy). ``trial`` selects one report by its key."""
    runs = _runs(root) if root is not None else (RUNS or Path("data/runs"))
    found = []
    for kind, pattern in (("development", "eval/*/*.json"), ("holdout", "holdout/*/*.json"), ("legacy", "eval/*.json")):
        for p in sorted(runs.glob(pattern)):
            found.append((str(p.relative_to(runs)).replace("\\", "/").removesuffix(".json"), kind, p))
    if trial:
        safe = "".join(ch for ch in trial if ch.isalnum() or ch in ".-_/")
        match = next(((k, kind, p) for k, kind, p in found if k == safe or (kind == "legacy" and k == "eval/" + safe)), None)
        if match is None or ".." in safe:
            return {"error": "NOT_FOUND"}
        rep = json.loads(match[2].read_text(encoding="utf-8"))
        for f in rep.get("folds", []):
            sim = f.get("simulation") or {}
            if "trades" in sim:
                sim["trades"] = sim["trades"][-200:]
        return rep | {"key": match[0], "kind": match[1]}
    reports = []
    for key, kind, p in found:
        try:
            reports.append(_report_summary(json.loads(p.read_text(encoding="utf-8")), key, kind))
        except (ValueError, OSError):
            continue
    return {"reports": reports, "holdout": registry_manifest(runs)}


def registry_manifest(runs: Path) -> dict | None:
    from .quant import registry
    return registry.holdout_manifest(runs)


def decision_view(root: Path, decision_id: str | None = None) -> dict:
    """One decision record by id (default: the newest in the timeline) with its diagnostics, if any."""
    runs = _runs(root)
    ids = [e["decision_id"] for e in decisions.timeline(root, 30) if e.get("decision_id")]
    if not ids and decision_id is None:
        return {"decision": None, "available": [], "diagnostics": None}
    d = decisions.load(root, decision_id or ids[0], runs)
    if d is None:
        return {"decision": None, "available": ids, "error": "NOT_FOUND", "diagnostics": None}
    diag = None
    rel = d.get("diagnostic_artifact")
    if rel and (runs / rel).exists():
        try:
            diag = json.loads((runs / rel).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            diag = {"error": "unreadable"}
    return {"decision": d, "available": ids, "diagnostics": diag}


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
                b = buildinfo.build_info()
                return self._json(200, {"service": "up", "live_orders": False, "git_head": b["git_head"],
                                        "source_digest": b["source_digest_at_start"],
                                        "source_changed_since_start": b["source_changed_since_start"]})
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
                if path == "/api/version":
                    return self._json(200, buildinfo.build_info() | {"private_root": str(app.root.resolve()),
                                                                      "market_root": str(app.market.resolve())})
                if path == "/api/status":
                    return self._json(200, status(app.root, app.market))
                if path == "/api/data":
                    return self._json(200, _jsonable(data_coverage(app.market)))
                if path == "/api/universe":
                    d = q.get("date", [None])[0]
                    return self._json(200, universe_view(app.market, date.fromisoformat(d) if d else None, app.root))
                if path == "/api/evaluation":
                    return self._json(200, _jsonable(evaluation_view(q.get("trial", [None])[0], app.root)))
                if path == "/api/decision":
                    return self._json(200, _jsonable(decision_view(app.root, q.get("id", [None])[0])))
                if path == "/api/research":
                    return self._json(200, _jsonable(research_view(app.root, app.market)))
                if path == "/api/requests":
                    return self._json(200, _jsonable(requests_view(app.root)))
                if path == "/api/config":
                    from .quant import candidates
                    pol = service.policy(app.root)
                    eff = service.effective_policy(app.root, pol)
                    return self._json(200, {"policy": pol, "policy_effective": eff.to_json(), "policy_digest": eff.digest(),
                                            "bounds": service.POLICY_BOUNDS, "nullable": sorted(service.NULLABLE),
                                            "unsupported": service.UNSUPPORTED_POLICY_KEYS,
                                            "candidates": {k: {"implemented": v.implemented, "horizons": list(v.horizons),
                                                               "reason": v.reason} for k, v in candidates.REGISTRY.items()},
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
