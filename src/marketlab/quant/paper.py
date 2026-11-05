"""Forward paper ledger: a deterministic replay of recorded paper orders over stored exchange files.

There is no mutable account file. The ledger is rebuilt, whenever needed, from two immutable inputs:
* the decision records whose action is PAPER_PLAN (written once, hashed, only possible with a verified promotion),
  each carrying the orders frozen after that session's close (new intents, exit decisions); and
* the stored bhavcopies of the following sessions, read by the same EXEC.v1 ledger the replay uses (fills at the
  next open within the limit, deferrals, blocked exits, actions, settlement, daily NAV).

``snapshot`` writes the state after each session once (runs/paper/<day>.json). A later rebuild that disagrees with a
stored snapshot is reported as REVISED (an input file changed after the fact), never silently overwritten.
Simulated only: nothing here can reach a broker.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields as dc_fields, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from .. import decisions
from .ledger import ExecutionPolicy, Intent, Ledger
from .sessions import exchange_sessions

FOLDER = "paper"


def orders_by_day(root: Path) -> dict[date, dict]:
    out = {}
    for e in decisions.timeline(root, 100_000):
        if e.get("action") != "PAPER_PLAN" or not e.get("decision_id"):
            continue
        rec = decisions.load(root, e["decision_id"])
        if rec is None or rec.get("integrity") != "OK":
            continue
        out[date.fromisoformat(rec["day"])] = rec
    return dict(sorted(out.items()))


def intent_to_json(it: Intent) -> dict:
    d = {f.name: getattr(it, f.name) for f in dc_fields(it)}
    d.update(decision_day=it.decision_day.isoformat(), reserved=str(it.reserved))
    return d


def _intent(d: dict, k: int, delay: int) -> Intent:
    return Intent(d["intent_id"], d["isin"], d.get("symbol", ""), date.fromisoformat(d["decision_day"]), int(d["q"]),
                  float(d["ref_close"]), float(d["limit"]), float(d["slip_in"]), float(d["slip_out"]),
                  Decimal(d["reserved"]), k + delay, d.get("forecast", {}))


def rebuild(panel, calendar, root: Path, through: date, *, actions=None, h: int | None = None) -> dict | None:
    """The paper account after ``through``'s close and its evening orders, or None before the first paper order."""
    recs = orders_by_day(root)
    recs = {d: r for d, r in recs.items() if d <= through}
    if not recs:
        return None
    start = next(iter(recs))
    first = recs[start]
    ex = ExecutionPolicy(**{k: v for k, v in (first.get("execution") or {}).items() if k in {f.name for f in dc_fields(ExecutionPolicy)}})
    led = Ledger(first["policy"]["W"], ex)
    stored = set(panel.sessions(None, through))
    # index sessions from the panel's first stored session, exactly as the replay dataset does, so that lot review
    # indices and the decision's session index agree
    sessions = exchange_sessions(calendar, min(stored), through, stored)[0]
    k_start = sessions.index(start)
    idx = panel.index_levels(first.get("index_name", "Nifty 50"))
    unchecked = panel.unchecked_days(start, through)
    horizon = h or int(first.get("h", 20))
    for k in range(k_start, len(sessions)):
        day = sessions[k]
        have = day in stored
        bars = {i: b for i, b in panel.cross_section(day)} if have else {}
        iopen = (idx.get(day) or (None, None))[0]
        held = list(led.lots)
        fs = {i: v for i in held if (v := panel.implied_factors(i, day, day).get(day))}
        dd = {i: v[day] for i in held if (v := panel.discontinuities(i, day, day)) and day in v}
        led.apply_actions(k, day, fs, day in unchecked, None, dd or None, actions)
        led.execute_exits(k, day, have, bars, iopen)
        led.execute_entries(k, day, have, bars, horizon, iopen)
        led.mark(k, day, {i: b.close for i, b in bars.items()}, have)
        led.settle(k, day)
        rec = recs.get(day)
        if rec:
            for x in rec.get("orders", {}).get("exits", []):
                lot = led.lots.get(x["isin"])
                if lot and not lot.exit_pending:
                    lot.exit_pending, lot.exit_reason, lot.exit_decided_index = True, x.get("reason"), k
                    led.event("EXIT_DECIDED", day, isin=x["isin"], reason=x.get("reason"), decision_id=rec["decision_id"])
            for d in rec.get("orders", {}).get("intents", []):
                led.add_intent(_intent(d, k, ex.entry_delay_sessions))
    return {"ledger": led, "sessions": sessions, "start": start, "through": through, "k": len(sessions) - 1,
            "decisions": [r["decision_id"] for r in recs.values()]}


def state(led: Ledger) -> dict:
    nav = led.nav[-1] if led.nav else None
    return {"nav": nav, "cash_settled": str(led.cash), "blocked": str(led.reserved()),
            "unsettled": [{"amount": str(r["amount"]), "usable_from_index": r["usable_from"]} for r in led.receivables],
            "dividends_receivable": [dict(x, amount=str(x["amount"])) for x in led.dividends],
            "positions": [{"isin": lot.isin, "q": lot.q, "units": lot.units, "entry_day": lot.entry_day.isoformat(),
                           "entry_price": lot.entry_price, "last_close": lot.last_close, "exit_pending": lot.exit_pending,
                           "flags": sorted(lot.action_flags)} for lot in led.lots.values()],
            "pending_intents": [intent_to_json(i) for i in led.intents.values()],
            "trades": len(led.trades), "realized_net": round(sum(t["net_rupees"] for t in led.trades), 2)}


def snapshot(root: Path, built: dict) -> dict:
    """Write the state after ``through`` once; compare with an existing snapshot instead of replacing it."""
    led = built["ledger"]
    # the whole NAV history and every fill are covered, so a revised price on any earlier day changes the hash
    st = state(led) | {"day": built["through"].isoformat(), "decisions": built["decisions"], "nav_history": led.nav,
                       "fills": [e for e in led.events if e["event"] in ("FILLED", "EXIT_FILLED")]}
    body = json.dumps(st, sort_keys=True, default=str)
    st["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    path = decisions.runs_dir(root) / FOLDER / f"{built['through'].isoformat()}.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        return {"path": str(path), "status": "UNCHANGED" if old.get("sha256") == st["sha256"] else "REVISED",
                "stored_sha256": old.get("sha256"), "rebuilt_sha256": st["sha256"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(st, f, indent=1, sort_keys=True, default=str)
    return {"path": str(path), "status": "WRITTEN", "sha256": st["sha256"]}


def status(panel, calendar, root: Path, configured_capital: float) -> dict:
    """What the dashboard shows: the rebuilt account through the last stored session, or that none exists yet."""
    days = panel.sessions() if panel is not None else []
    built = rebuild(panel, calendar, root, days[-1]) if days else None
    if built is None:
        return {"kind": "SIMULATED_PAPER", "state": "NO_PAPER_ORDERS_YET", "configured_capital": configured_capital,
                "cash": None, "positions": None, "pnl": None,
                "note": "The forward paper ledger starts with the first PAPER_PLAN decision, which needs a verified "
                        "promotion. Until then there is no simulated cash or position to show. Not your real account."}
    led = built["ledger"]
    nav = led.nav[-1]["nav"] if led.nav else float(led.W)
    return {"kind": "SIMULATED_PAPER", "state": "ACTIVE", "since": built["start"].isoformat(), "through": built["through"].isoformat(),
            "configured_capital": float(led.W), "cash": str(led.cash), "positions": state(led)["positions"],
            "nav": nav, "pnl": round(nav - float(led.W), 2), "trades": len(led.trades),
            "note": "Rebuilt from recorded paper orders and stored exchange files (deterministic). Not your real account."}
