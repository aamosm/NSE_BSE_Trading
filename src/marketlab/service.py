"""Supervised scheduler: one process that collects, builds daily inputs and reports health.

States (``service_state.json``, shown in the phone app):
* ``state``: RUNNING, AUTH_REQUIRED (broker-dependent jobs paused until the owner logs in; public data
  continues) or DEGRADED (a job failed or a provider circuit breaker is open).
* ``analysis``: ACTIVE or PAUSED (owner control; pauses paper analysis only, never data collection).

Each job runs at most once per due window, records its outcome, and failures open a per-provider
circuit breaker with exponential back-off (no tight retry loops). A single-instance lock prevents
duplicate schedulers. There is no order capability anywhere in this process.

Paper analysis: each trading day the scheduler records one decision through ``decisions.record`` (the same
recorder the CLI and the Controls tab use). Without a verified promotion record it is a WAIT with reason
MODEL_NOT_PROMOTED; the gate is never opened by a flag.
"""
from __future__ import annotations

import json
import os
import time
import uuid
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


# ---- owner policy (bounded, validated) and job requests from the dashboard ---------------------------------

POLICY_FILE = "policy.json"
# K and cap_fraction default to None: the spec 5.4 tier for the capital applies until the owner sets a value.
POLICY_DEFAULTS = {"capital": 10000.0, "K": None, "cap_fraction": None, "reserve_fraction": 0.2, "v_min_crore": 5.0,
                   "h": 20, "candidate": "A", "symbols": [], "families": {"A": True, "B": False, "C": False},
                   "risk_multiplier": 1.0}
POLICY_BOUNDS = {"capital": (1000.0, 1e8), "K": (1, 10), "cap_fraction": (0.05, 1.0), "reserve_fraction": (0.0, 0.9),
                 "v_min_crore": (0.1, 1000.0), "h": (5, 250), "risk_multiplier": (0.25, 1.0)}
NULLABLE = {"K", "cap_fraction"}
# Stored but not read by any job yet: the scheduler collects broker data for its --symbols argument.
UNSUPPORTED_POLICY_KEYS = {"symbols": "stored only; the scheduler uses its --symbols argument"}
REQUEST_KINDS = {"prepare", "fetch_public", "build_master", "panel_build", "decide", "evaluate", "rank"}
REQUESTS_DIR = "requests"
IDEMPOTENT_REQUESTS = {"prepare", "fetch_public", "build_master", "panel_build", "rank"}  # same inputs, same result
MAX_REQUEST_ATTEMPTS = 2
PROCESS_TOKEN = uuid.uuid4().hex  # identifies this scheduler process in request files (restart detection)


def policy(root: Path) -> dict:
    saved = read_json(root / POLICY_FILE, {})
    out = dict(POLICY_DEFAULTS)
    out["families"] = dict(POLICY_DEFAULTS["families"])
    for k, v in saved.items():
        if k == "families" and isinstance(v, dict):
            out["families"].update({f: bool(v.get(f, out["families"][f])) for f in out["families"]})
        elif k in out:
            out[k] = v
    return out


def effective_policy(root: Path, saved: dict | None = None):
    """The allocator policy the next decision or evaluation will use (persisted with each of them)."""
    from .quant.allocate import Policy
    return Policy.from_owner(saved or policy(root))


def set_policy(root: Path, updates: dict) -> dict:
    """Validate and store owner policy edits. Unknown keys, out-of-range values, unimplemented candidates and
    families, and horizons outside the candidate's registered trials are refused."""
    import re
    from .quant import candidates
    current = policy(root)
    for k, v in updates.items():
        if k not in POLICY_DEFAULTS:
            raise ValueError(f"unknown policy key {k}")
        if k in NULLABLE and v is None:
            current[k] = None  # back to the spec default for the capital
            continue
        if k in POLICY_BOUNDS:
            lo, hi = POLICY_BOUNDS[k]
            try:
                num = int(v) if isinstance(lo, int) else float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number") from None
            if not lo <= num <= hi:
                raise ValueError(f"{k} must be between {lo} and {hi}")
            current[k] = num
        elif k == "candidate":
            if v not in candidates.REGISTRY:
                raise ValueError("candidate must be A, B or C")
            candidates.require(v)  # B and C: UNIMPLEMENTED
            current[k] = v
        elif k == "symbols":
            if not isinstance(v, list) or len(v) > 50 or not all(isinstance(x, str) and re.fullmatch(r"[A-Z0-9&.-]{1,20}", x) for x in v):
                raise ValueError("symbols must be up to 50 NSE symbols")
            current[k] = sorted(set(v))
        elif k == "families":
            if not isinstance(v, dict):
                raise ValueError("families must be an object")
            fam = {f: bool(v.get(f, current["families"][f])) for f in current["families"]}
            for f, on in fam.items():
                if on and not candidates.REGISTRY[f].implemented:
                    raise ValueError(f"UNIMPLEMENTED: family {f} cannot be enabled: {candidates.REGISTRY[f].reason}")
            current["families"] = fam
    candidates.require(current["candidate"], int(current["h"]))  # e.g. A is registered for h = 20 and 60 only
    current["changed_at"] = now().isoformat()
    atomic_json(root / POLICY_FILE, current)
    return current


def submit_request(root: Path, kind: str, args: dict | None = None, at=None) -> dict:
    """Queue a job for the scheduler process (the web server never runs heavy work itself)."""
    import uuid
    if kind not in REQUEST_KINDS:
        raise ValueError(f"unknown request kind {kind}")
    args = args or {}
    clean = {}
    if "date" in args:
        clean["date"] = date.fromisoformat(str(args["date"])).isoformat()
    if kind in ("evaluate", "decide"):
        from .quant import candidates
        pol = policy(root)
        clean["candidate"] = str(args.get("candidate", pol["candidate"]))[:1]
        clean["h"] = int(args.get("h", pol["h"]))
        candidates.require(clean["candidate"], clean["h"])  # Unimplemented (a ValueError) -> HTTP 400
    req = {"id": uuid.uuid4().hex[:12], "kind": kind, "args": clean, "submitted_at": (timestamp(at) if at else now()).isoformat(),
           "state": "QUEUED", "attempt": 0}
    folder = root / REQUESTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / f"{req['submitted_at'][:19].replace(':', '')}_{req['id']}.json", req)
    return req


def list_requests(root: Path, limit=30) -> list:
    folder = root / REQUESTS_DIR
    if not folder.exists():
        return []
    out = []
    for p in sorted(folder.glob("*.json"))[-limit:]:
        out.append(read_json(p, {"id": p.stem, "state": "UNREADABLE"}))
    return list(reversed(out))


def build_ranking(root: Path, market: Path, calendar, *, h: int | None = None, candidate: str | None = None,
                  bootstrap: int = 50, progress=None, origin: str = "cli", capital: float | None = None) -> dict:
    """Today's research ranking (quant.ranking) with the saved policy, the corporate-action registry and rule files
    admitted by the exchange server's timestamp before the entry session opens (RECONSTRUCTED; labelled).

    capital overrides the saved policy's capital for this run only (recorded in the artifact as policy_source)."""
    from . import action_registry
    from .quant import evaluate as qevaluate, ranking as qranking, universe as quniverse
    from .quant.panel import Panel
    from .quant.universe import ScreenPolicy
    pol = policy(root)
    if capital is not None:
        lo, hi = POLICY_BOUNDS["capital"]
        if not lo <= float(capital) <= hi:
            raise ValueError(f"CAPITAL_OUT_OF_RANGE: {lo:.0f}..{hi:.0f}")
        pol = dict(pol, capital=float(capital))
    eff = effective_policy(root, pol)
    cfg = qevaluate.Config(candidate=candidate or pol["candidate"], h=int(h or pol["h"]), W=eff.W,
                           screen=ScreenPolicy(v_min=pol["v_min_crore"] * 1e7, W=eff.W), policy=eff)
    panel_path = market / "panel.sqlite3"
    if not panel_path.exists():
        raise ValueError("PANEL_NOT_BUILT: build the price panel first")
    pn = Panel(panel_path)
    try:
        acts = action_registry.load_index(market, pn)
        ri = lambda d: quniverse.rule_inputs_for(market, d, calendar, "RECONSTRUCTED")  # noqa: E731
        return qranking.build(pn, cfg, root=root, calendar=calendar, rule_inputs_fn=ri, actions=acts, bootstrap=bootstrap,
                              progress=progress, extra={"origin": origin} |
                              ({"policy_source": "capital-override"} if capital is not None else {}))
    finally:
        pn.close()


def _run_request(ctx, req: dict) -> dict:
    from datetime import date as _date
    kind, args = req["kind"], req.get("args", {})
    day = _date.fromisoformat(args["date"]) if args.get("date") else now().date()
    if kind == "prepare":
        return {"result": job_prepare(ctx, {"key": f"request:{req['id']}", "day": day})}
    if kind == "fetch_public":
        from . import sources
        out = sources.collect(ctx.market, day, pause=ctx.pause)
        return {"result": {r["source"]: r["result"] for r in out}}
    if kind == "build_master":
        from . import master
        return {"result": master.build_master(ctx.market, day, ctx.cal)}
    if kind == "panel_build":
        from .quant import panel as qpanel
        return {"result": qpanel.build(ctx.market, calendar=ctx.cal)}
    if kind == "rank":
        out = build_ranking(ctx.root, ctx.market, ctx.cal, h=args.get("h"), origin="controls")
        return {"result": {k: out.get(k) for k in ("day", "status", "counts", "digest")} | {"forward": out.get("forward")}}
    pol = policy(ctx.root)
    from . import decisions
    from .quant import decide as qdecide, evaluate as qevaluate, universe as quniverse
    from .quant.panel import Panel
    from .quant.universe import ScreenPolicy
    cfg = qevaluate.Config(candidate=args.get("candidate", pol["candidate"]), h=int(args.get("h", pol["h"])), W=float(pol["capital"]),
                           screen=ScreenPolicy(v_min=pol["v_min_crore"] * 1e7, W=float(pol["capital"])),
                           policy=effective_policy(ctx.root, pol))
    panel_path = ctx.market / "panel.sqlite3"
    pn = Panel(panel_path) if panel_path.exists() else None
    try:
        from . import action_registry
        acts = action_registry.load_index(ctx.market, pn)
        if kind == "decide":  # forward decision: rule files received before the decision only
            from .quant import paper
            ri = lambda d: quniverse.rule_inputs_for(ctx.market, d, ctx.cal, "RECEIPT")  # noqa: E731
            out = qdecide.run(pn, cfg, root=ctx.root, origin="controls", families=pol["families"], rule_inputs_fn=ri,
                              calendar=ctx.cal, extra={"request_id": req["id"]}, actions=acts)
            snap = None
            if pn is not None and pn.sessions():
                built = paper.rebuild(pn, ctx.cal, ctx.root, pn.sessions()[-1], actions=acts)
                snap = paper.snapshot(ctx.root, built)["status"] if built else None
            return {"result": {k: out.get(k) for k in ("decision_id", "day", "action", "reasons")} | {"paper_snapshot": snap}}
        if pn is None:
            raise ValueError("PANEL_NOT_BUILT: build the price panel first")
        ri = lambda d: quniverse.rule_inputs_for(ctx.market, d, ctx.cal, cfg.availability)  # noqa: E731
        out = qevaluate.walk_forward(pn, cfg, runs=decisions.runs_dir(ctx.root), calendar=ctx.cal, rule_inputs_fn=ri,
                                     progress=lambda *_: None, actions=acts)
        return {"result": {k: out.get(k) for k in ("trial_id", "run_id", "folds_done", "n_trades", "net_rupees_total")}
                | {"verdict": (out.get("promotion") or {}).get("verdict")}}
    finally:
        if pn is not None:
            pn.close()


def recover_requests(ctx, at=None) -> list[str]:
    """RUNNING requests whose worker is gone (a previous scheduler process, or a dead thread in this one) are
    marked INTERRUPTED. Idempotent file and panel jobs are re-queued under the same request id (at most
    MAX_REQUEST_ATTEMPTS starts); decisions and evaluations are not re-run automatically: resubmit them."""
    folder = ctx.root / REQUESTS_DIR
    if not folder.exists():
        return []
    worker = getattr(ctx, "_request_thread", None)
    alive = worker is not None and worker.is_alive()
    when = (timestamp(at) if at else now()).isoformat()
    out = []
    for p in sorted(folder.glob("*.json")):
        req = read_json(p, {})
        if req.get("state") != "RUNNING":
            continue
        if req.get("worker") == PROCESS_TOKEN and alive:
            continue
        reason = "SCHEDULER_RESTARTED" if req.get("worker") != PROCESS_TOKEN else "WORKER_THREAD_ENDED"
        history = list(req.get("history", [])) + [{"state": "INTERRUPTED", "at": when, "reason": reason,
                                                   "started_at": req.get("started_at"), "worker_pid": req.get("worker_pid")}]
        req["history"] = history
        if req.get("kind") in IDEMPOTENT_REQUESTS and int(req.get("attempt", 1)) < MAX_REQUEST_ATTEMPTS:
            req["state"] = "QUEUED"
        else:
            req.update(state="INTERRUPTED", finished_at=when,
                       error=f"{reason}: the worker stopped before finishing; not retried automatically "
                             "(decisions and evaluations are immutable records; resubmit to run again)")
        atomic_json(p, req)
        out.append(req["id"])
    return out


def process_requests(ctx, at=None) -> list:
    """Run queued dashboard requests one at a time in a background thread; results are written back to their files."""
    import threading
    folder = ctx.root / REQUESTS_DIR
    if not folder.exists():
        return []
    worker = getattr(ctx, "_request_thread", None)
    if worker is not None and worker.is_alive():
        return []
    recover_requests(ctx, at)
    queued = [p for p in sorted(folder.glob("*.json")) if read_json(p, {}).get("state") == "QUEUED"]
    if not queued:
        return []
    path = queued[0]
    req = read_json(path, {})
    req.update(state="RUNNING", started_at=(timestamp(at) if at else now()).isoformat(), worker=PROCESS_TOKEN,
               worker_pid=os.getpid(), attempt=int(req.get("attempt", 0)) + 1)
    atomic_json(path, req)

    def run():
        try:
            out = _run_request(ctx, req)
            req.update(state="DONE", finished_at=now().isoformat(), **out)
        except Exception as e:  # recorded, never raised into the scheduler
            req.update(state="FAILED", finished_at=now().isoformat(), error=f"{type(e).__name__}: {str(e)[:200]}")
        atomic_json(path, req)

    t = threading.Thread(target=run, daemon=True)
    ctx._request_thread = t
    t.start()
    return [req["id"]]


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
        scheduled_decision(ctx, args["day"], late_start=late)
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


def record_decision(ctx, day, action, reasons, symbols=(), late_start=False, extra=None):
    """The scheduler's daily record: one id per session (a restart re-uses it), via the shared recorder."""
    from . import decisions
    body = {"day": day.isoformat(), "action": action, "reasons": list(reasons), "symbols": list(symbols),
            "late_start": bool(late_start), "model_id": None, **(extra or {})}
    return decisions.record(ctx.root, body, origin="scheduler", decision_id=decisions.scheduled_id(day), at=now())


def scheduled_decision(ctx, day, late_start=False):
    """Gate order of spec 5.2 for the configured candidate: an unimplemented candidate, a disabled family or the
    absence of a verified promotion record each give a WAIT without fitting anything; with a verified promotion
    the full decision is queued as a request (it can take minutes and must not block the tick)."""
    from . import decisions
    from .quant import candidates, registry
    pol = policy(ctx.root)
    eff = effective_policy(ctx.root, pol)
    extra = {"candidate": pol["candidate"], "h": pol["h"], "policy": eff.to_json(), "policy_digest": eff.digest()}
    try:
        spec = candidates.require(pol["candidate"], int(pol["h"]))
    except candidates.Unimplemented:
        return record_decision(ctx, day, "WAIT", ["UNIMPLEMENTED_CANDIDATE"], ctx.symbols, late_start, extra)
    if not pol["families"].get(spec.family, False):
        return record_decision(ctx, day, "WAIT", ["FAMILY_DISABLED_BY_OWNER"], ctx.symbols, late_start, extra)
    promo, problems = registry.verified_promotion(decisions.runs_dir(ctx.root), pol["candidate"], int(pol["h"]), eff.digest())
    if promo is None:
        return record_decision(ctx, day, "WAIT", ["MODEL_NOT_PROMOTED"], ctx.symbols, late_start,
                               extra | {"promotion_check": problems})
    return submit_request(ctx.root, "decide", {"candidate": pol["candidate"], "h": pol["h"]})


# ---- tick ----------------------------------------------------------------------------------------

class Context:
    def __init__(self, root: Path, market: Path, symbols=(), calendar=None, backups: Path | None = None, pause=1.5):
        self.root, self.market, self.symbols = root, market, list(symbols)
        if calendar is None:
            from . import sources
            calendar, self.calendar_report = sources.load_calendar_for(market)
        else:
            self.calendar_report = {"source": "SUPPLIED"}
        self.cal = calendar
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
    started = process_requests(ctx, at)
    if started:
        st["last_request_started"] = {"id": started[0], "at": at.isoformat()}
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
    st["calendar"] = ctx.calendar_report
    st["interval_seconds"] = getattr(ctx, "interval", None)
    st["process"] = {"pid": os.getpid(), "token": PROCESS_TOKEN[:8], "root": str(ctx.root.resolve()),
                     "market": str(ctx.market.resolve())}
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
    ctx.interval = interval
    with single_instance(ctx.root / LOCK_FILE):
        n = 0
        while iterations is None or n < iterations:
            tick(ctx)
            n += 1
            if iterations is None or n < iterations:
                sleep(interval)
