"""Supervised scheduler: one process that collects, builds daily inputs and reports health.

States (``service_state.json``, shown in the phone app):
* ``state``: RUNNING, AUTH_REQUIRED (broker-dependent jobs paused until the owner logs in; public data
  continues) or DEGRADED (a job failed or a provider circuit breaker is open).
* ``analysis``: ACTIVE or PAUSED (owner control; pauses paper analysis only, never data collection).

Each job runs at most once per due window, records its outcome, and failures open a per-provider
circuit breaker with exponential back-off (no tight retry loops). A single-instance lock prevents
duplicate schedulers. There is no order capability anywhere in this process.

Paper analysis is a placeholder until a validated model exists: each trading day it records one WAIT
decision with reason MODEL_NOT_VALIDATED, assembled from reason codes, so the timeline is honest.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, time as clock, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from . import login
from .common import IST, atomic_json, now, timestamp
from .kite import AuthenticationRequired, KiteError, NoRedirect
from .rules.calendar import MarketCalendar
from .rules.types import Exchange, RuleUnknown
from .store import Store

STATE_FILE = "service_state.json"
BROKER_LEAD = timedelta(minutes=55)  # first broker read at 08:05 on a regular day (owner logs in at 08:00)
EOD_START = clock(16, 45)
CATCH_UP_SESSIONS = 5
GAP_THRESHOLD = timedelta(minutes=5)  # a longer silence between ticks is recorded (sleep, shutdown, crash)
CONTROL_FILE = "control.json"
LOCK_FILE = "service.lock"
BREAKER_BASE = timedelta(minutes=15)
BREAKER_MAX = timedelta(hours=6)
ALERT_TEXT = {
    "AUTH_REQUIRED": "MarketLab: Kite login needed. Open the app and tap Log in to resume broker collection.",
    "DEGRADED": "MarketLab: a data job is failing; open the app for the affected source.",
    "RECOVERED": "MarketLab: all jobs healthy again.",
}


@contextmanager
def single_instance(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another MarketLab service already holds the lock") from None
        yield
    finally:
        f.close()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (ValueError, OSError):
        return default


def control(root: Path) -> dict:
    c = read_json(root / CONTROL_FILE, {})
    return {"analysis_paused": c.get("analysis_paused") is True, "changed_at": c.get("changed_at")}


def set_paused(root: Path, paused: bool, at=None) -> dict:
    value = {"analysis_paused": bool(paused), "changed_at": (timestamp(at) if at else now()).isoformat()}
    atomic_json(root / CONTROL_FILE, value)
    return value


# ---- schedule ------------------------------------------------------------------------------------

def _trading(cal: MarketCalendar, d: date):
    try:
        return cal.is_trading_day(Exchange.NSE, d)
    except RuleUnknown:
        return None  # year not loaded: unknown, so session-dependent jobs do not run


def due_jobs(at: datetime, cal: MarketCalendar, last: dict) -> list[tuple[str, dict]]:
    """Jobs due at ``at`` with their arguments. ``last`` maps job key -> last run ISO time."""
    t, d = at.time(), at.date()
    jobs = []

    def every(key, minutes):
        prev = last.get(key)
        return prev is None or at - timestamp(prev) >= timedelta(minutes=minutes)

    def once(key):
        return key not in last

    today_trading = _trading(cal, d)
    if today_trading:
        try:
            opens = cal.session_open(Exchange.NSE, d)
        except RuleUnknown:
            opens = None
        if opens and (datetime.combine(d, opens, IST) - BROKER_LEAD).time() <= t <= clock(16, 30) \
                and every("broker", 5):
            jobs.append(("broker", {"key": "broker"}))
    if t >= clock(18, 0) and once(f"broker_daily:{d}"):
        jobs.append(("broker", {"key": f"broker_daily:{d}"}))
    # End-of-day exchange files: today's from 16:45 (bhavcopies were published at about 16:35 IST, sec_list
    # 18:00, REG1_IND 19:50, index closes 23:20, delivery data 23:55 on 4 Nov 2026), and catch-up for up to
    # CATCH_UP_SESSIONS earlier sessions not yet complete (laptop off or asleep). Retried every 30 minutes.
    targets = [d] if today_trading and t >= EOD_START else []
    p = d
    for _ in range(CATCH_UP_SESSIONS):
        try:
            p = cal.previous_trading_day(Exchange.NSE, p)
        except RuleUnknown:
            break
        targets.append(p)
    for target in targets:
        if f"public_eod_done:{target}" not in last and every(f"public_eod:{target}", 30):
            jobs.append(("public_eod", {"key": f"public_eod:{target}", "day": target}))
    if t >= clock(7, 0) and once(f"public_daily:{d}"):
        jobs.append(("public_daily", {"key": f"public_daily:{d}", "day": d}))
    if clock(6, 0) <= t <= clock(23, 45) and every("feeds", 30):
        jobs.append(("feeds", {"key": "feeds"}))
    if today_trading and clock(8, 0) <= t <= clock(15, 30) and once(f"prepare:{d}"):
        jobs.append(("prepare", {"key": f"prepare:{d}", "day": d}))
    if t >= clock(23, 30) and once(f"backup:{d}"):
        jobs.append(("backup", {"key": f"backup:{d}", "day": d}))
    return jobs


# ---- jobs ----------------------------------------------------------------------------------------

def job_broker(ctx, args):
    from . import cli
    if login.session_status(ctx.root)["state"] != "AUTHENTICATED" or ctx.state.get("auth_invalid"):
        return "SKIPPED_AUTH_REQUIRED"
    cli.collect_once(ctx.root, ctx.symbols, instruments=args["key"].startswith("broker_daily"))
    return "OK"


def job_public_eod(ctx, args):
    from . import sources
    ids = [s.id for s in sources.REGISTER if s.dated and s.status == "WORKS"]
    out = sources.collect(ctx.market, args["day"], ids, pause=ctx.pause)
    failed = [r["source"] for r in out if r["result"] in ("FAILED", "SCHEMA_CHANGED")]
    waiting = [r["source"] for r in out if r["result"] == "NOT_PUBLISHED"]
    if failed:
        raise JobFailed("SOURCE_FAILED:" + ",".join(failed))
    if not waiting:
        return "OK"
    if (now().date() - args["day"]).days >= 2:  # still unpublished two days later: recorded as missing, not retried
        return "OK_MISSING:" + ",".join(waiting)
    return "WAITING:" + ",".join(waiting)


def job_public_daily(ctx, args):
    from . import sources
    ids = [s.id for s in sources.REGISTER if not s.dated and s.status == "WORKS" and s.layer != "events"]
    ids += ["nse_rss_corporate_actions"]
    out = sources.collect(ctx.market, args["day"], ids, pause=ctx.pause)
    failed = [r["source"] for r in out if r["result"] in ("FAILED", "SCHEMA_CHANGED")]
    if failed:
        raise JobFailed("SOURCE_FAILED:" + ",".join(failed))
    return "OK"


def job_feeds(ctx, args):
    from . import news, sources
    db = sources.catalog(ctx.market)
    count = 0
    try:
        for spec in sources.REGISTER:
            if spec.layer == "events" and spec.ext == "xml" and spec.status == "WORKS":
                raw = news.fetch_feed(spec.url)
                count += len(news.ingest_feed(db, raw, "public:" + spec.id))
                time.sleep(ctx.pause)
    finally:
        db.close()
    return f"OK:{count}"


def job_prepare(ctx, args):
    """Security master and watchlist rule inputs for today's session; then the paper-analysis step."""
    from . import master
    opens = datetime.combine(args["day"], ctx.cal.session_open(Exchange.NSE, args["day"]), IST)
    cutoff = max(opens, now())  # a late start may use files received before the actual decision time
    late = cutoff - opens > timedelta(minutes=15)
    summary = master.build_master(ctx.market, args["day"], ctx.cal, cutoff=cutoff)
    built, blocked = 0, {}
    for sym in ctx.symbols:
        name = sym.split(":", 1)[-1]
        if not sym.startswith("NSE:"):
            blocked[name] = "BSE_SNAPSHOT_NOT_BUILT"
            continue
        snap, prov = master.build_nse_snapshot(ctx.market, name, args["day"], ctx.cal, cutoff=cutoff)
        if snap is None:
            blocked[name] = prov.get("blocker", "UNKNOWN")
        else:
            built += 1
            ctx.catalog_append("instrument_snapshot", name, {"snapshot": master.snapshot_json(snap), "provenance": prov})
    if not control(ctx.root)["analysis_paused"]:
        record_decision(ctx, args["day"], "WAIT", ["MODEL_NOT_VALIDATED"], symbols=ctx.symbols, late_start=late)
    return f"OK:master={summary['listings']},snapshots={built},blocked={len(blocked)}" + (",late" if late else "")


def job_backup(ctx, args):
    dest = ctx.backups / args["day"].isoformat()
    for name, path in (("evidence", ctx.root / "evidence.sqlite3"), ("catalog", ctx.market / "catalog.sqlite3")):
        if path.exists():
            s = Store(path)
            try:
                s.backup(dest / f"{name}.sqlite3")
            finally:
                s.close()
    return "OK"


JOBS = {"broker": job_broker, "public_eod": job_public_eod, "public_daily": job_public_daily, "feeds": job_feeds,
        "prepare": job_prepare, "backup": job_backup}
PROVIDER = {"broker": "kite", "public_eod": "exchange_files", "public_daily": "exchange_files",
            "feeds": "exchange_feeds", "prepare": "local", "backup": "local"}


class JobFailed(RuntimeError):
    pass


def record_decision(ctx, day, action, reasons, symbols=(), late_start=False):
    from .research import explain
    entry = {"day": day.isoformat(), "action": action, "reasons": reasons, "symbols": list(symbols),
             "explanation": explain({"reasons": reasons}), "model_id": None, "simulated": True, "live_orders": False,
             "late_start": bool(late_start)}
    db = Store(ctx.root / "evidence.sqlite3")
    try:
        db.append("paper_decision", "marketlab:analysis", day.isoformat(), entry)
    finally:
        db.close()


# ---- tick ----------------------------------------------------------------------------------------

class Context:
    def __init__(self, root: Path, market: Path, symbols=(), calendar=None, backups: Path | None = None, pause=1.5):
        self.root, self.market, self.symbols = root, market, list(symbols)
        self.cal = calendar or MarketCalendar()
        self.backups = backups or root.parent / "backups"
        self.pause = pause
        self.state = read_json(root / STATE_FILE, {})

    def catalog_append(self, kind, subject, payload):
        from . import sources
        db = sources.catalog(self.market)
        try:
            db.append(kind, "marketlab", subject, payload)
        finally:
            db.close()


def _open_breaker(breakers, provider, at):
    b = breakers.get(provider, {"failures": 0})
    b["failures"] = b.get("failures", 0) + 1
    wait = min(BREAKER_BASE * (2 ** (b["failures"] - 1)), BREAKER_MAX)
    b["open_until"] = (at + wait).isoformat()
    breakers[provider] = b


def tick(ctx: Context, at=None, jobs=None) -> dict:
    at = timestamp(at) if at else now()
    jobs = jobs or JOBS
    st = ctx.state
    last, results, breakers = st.setdefault("last_run", {}), st.setdefault("jobs", {}), st.setdefault("breakers", {})
    prev_tick = st.get("last_tick_at")
    if prev_tick and at - timestamp(prev_tick) > GAP_THRESHOLD:
        gap = {"from": prev_tick, "to": at.isoformat(), "minutes": int((at - timestamp(prev_tick)).total_seconds() // 60)}
        st["last_gap"] = gap
        st["gaps"] = (st.get("gaps") or [])[-9:] + [gap]
    st["last_tick_at"] = at.isoformat()
    session = login.session_status(ctx.root, at)
    if session["state"] == "AUTHENTICATED" and st.get("auth_invalid") and st.get("auth_invalid_at", "") < (
            session.get("login_at") or ""):
        st.pop("auth_invalid", None)  # a newer login replaced the invalidated token
    for name, args in due_jobs(at, ctx.cal, last):
        provider = PROVIDER[name]
        b = breakers.get(provider)
        if b and timestamp(b["open_until"]) > at:
            results[name] = {"at": at.isoformat(), "result": "SKIPPED_BREAKER_OPEN"}
            continue
        try:
            outcome = jobs[name](ctx, args)
            results[name] = {"at": at.isoformat(), "result": outcome}
            if outcome != "SKIPPED_AUTH_REQUIRED":
                breakers.pop(provider, None)
                last[args["key"]] = at.isoformat()
            if name == "public_eod" and (outcome == "OK" or str(outcome).startswith("OK_MISSING")):
                last[f"public_eod_done:{args['day']}"] = at.isoformat()
        except AuthenticationRequired:
            st["auth_invalid"], st["auth_invalid_at"] = True, at.isoformat()
            results[name] = {"at": at.isoformat(), "result": "AUTH_REQUIRED"}
        except (JobFailed, KiteError, OSError, ValueError, RuntimeError, RuleUnknown) as e:
            label = str(e) if isinstance(e, JobFailed) else type(e).__name__
            results[name] = {"at": at.isoformat(), "result": "FAILED", "error": label[:200]}
            _open_breaker(breakers, provider, at)
    for k in [k for k in last if ":" in k and k.split(":", 1)[1] < (at.date() - timedelta(days=14)).isoformat()]:
        del last[k]  # keep the schedule memory small
    auth_ok = session["state"] == "AUTHENTICATED" and not st.get("auth_invalid")
    open_breakers = [p for p, b in breakers.items() if timestamp(b["open_until"]) > at]
    failing = [n for n, r in results.items() if r.get("result") == "FAILED"]
    previous = st.get("state")
    st["state"] = "AUTH_REQUIRED" if not auth_ok else "DEGRADED" if (open_breakers or failing) else "RUNNING"
    st["analysis"] = "PAUSED" if control(ctx.root)["analysis_paused"] else "ACTIVE"
    st["session"] = {k: v for k, v in session.items() if k != "login_at"} | ({"invalidated": True}
                                                                           if st.get("auth_invalid") else {})
    st["updated_at"] = at.isoformat()
    st["live_orders"] = False
    if previous != st["state"]:
        alert(ctx, st["state"] if st["state"] != "RUNNING" else ("RECOVERED" if previous else None))
    heartbeat(ctx, st, at)
    atomic_json(ctx.root / STATE_FILE, st)
    return st


def _https(url):
    u = urlsplit(url or "")
    return u.scheme == "https" and u.hostname and not u.username


def alert(ctx, kind):
    url = login.load_env(ctx.root).get("MARKETLAB_ALERT_URL")
    if not kind or not _https(url):
        return
    try:
        req = Request(url, data=ALERT_TEXT[kind].encode(), method="POST",
                      headers={"Content-Type": "text/plain; charset=utf-8", "Title": "MarketLab"})
        build_opener(NoRedirect()).open(req, timeout=10).close()
        ctx.state["last_alert"] = {"kind": kind, "ok": True}
    except (OSError, KiteError, ValueError):
        ctx.state["last_alert"] = {"kind": kind, "ok": False}  # delivery failures are visible in the app


def heartbeat(ctx, st, at):
    url = login.load_env(ctx.root).get("MARKETLAB_HEARTBEAT_URL")
    if not _https(url):
        return
    prev = st.get("heartbeat", {}).get("at")
    if prev and at - timestamp(prev) < timedelta(minutes=5):
        return
    suffix = "" if st["state"] == "RUNNING" else "/fail" if st["state"] == "DEGRADED" else ""
    try:
        build_opener(NoRedirect()).open(Request(url.rstrip("/") + suffix), timeout=10).close()
        st["heartbeat"] = {"at": at.isoformat(), "ok": True}
    except (OSError, KiteError, ValueError):
        st["heartbeat"] = {"at": at.isoformat(), "ok": False}


def run_forever(ctx: Context, interval=60, iterations=None, sleep=time.sleep):
    with single_instance(ctx.root / LOCK_FILE):
        n = 0
        while iterations is None or n < iterations:
            tick(ctx)
            n += 1
            if iterations is None or n < iterations:
                sleep(interval)
