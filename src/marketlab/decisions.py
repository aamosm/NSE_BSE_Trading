"""One identity for every decision attempt: the scheduler's daily check, a CLI ``decide`` and a Controls request.

Each attempt, including an early WAIT (insufficient history, no promoted model, unimplemented candidate), gets a
``decision_id``. Its full record is written once to ``runs/decisions/<decision_id>.json`` and never overwritten;
a summary carrying the same id and the record's SHA-256 is appended to the evidence timeline (kind
``paper_decision``, subject = session day). The dashboard's timeline and its "latest decision" both read that id,
so a WAIT can no longer appear in one view and not the other.

Diagnostics computed without a verified promotion (forecasts, a hypothetical plan) are stored separately under
``runs/diagnostics/<decision_id>.json`` and are referenced, never merged into the decision itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date
from pathlib import Path

from .common import atomic_json, now
from .store import Store

KIND = "paper_decision"
ORIGINS = ("scheduler", "cli", "controls")
ACTIONS = ("WAIT", "PAPER_PLAN")


def runs_dir(root: Path) -> Path:
    """Run artifacts live beside the private folder: data/private -> data/runs."""
    return root.parent / "runs"


def new_id(day: date, origin: str) -> str:
    return f"{day:%Y%m%d}-{origin}-{uuid.uuid4().hex[:8]}"


def scheduled_id(day: date) -> str:
    """The scheduler makes one decision per session; a restart re-uses the id (and the first record wins)."""
    return f"{day:%Y%m%d}-scheduler-daily"


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False).encode()


def _write_once(path: Path, value) -> str:
    """Write ``value`` unless the file exists; return the stored file's SHA-256 (first write wins)."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}")
        atomic_json(tmp, value)
        try:
            os.link(tmp, path)  # atomic create-if-absent; fails if another writer got there first
        except FileExistsError:
            pass
        except OSError:
            if not path.exists():
                os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(root: Path, body: dict, *, origin: str, decision_id: str | None = None, diagnostics: dict | None = None,
           runs: Path | None = None) -> dict:
    """Persist one decision attempt. ``body`` needs ``day`` (ISO date), ``action`` and ``reasons``.

    Returns the timeline entry (the same dict that was appended to the evidence store)."""
    if origin not in ORIGINS:
        raise ValueError(f"unknown decision origin {origin}")
    if body.get("action") not in ACTIONS:
        raise ValueError("action must be WAIT or PAPER_PLAN")
    if body["action"] == "PAPER_PLAN" and not body.get("promotion_id"):
        raise ValueError("PAPER_PLAN requires a verified promotion record")
    day = date.fromisoformat(str(body["day"]))
    did = decision_id or new_id(day, origin)
    runs = runs or runs_dir(root)
    full = {"decision_id": did, "origin": origin, **body, "simulated": True, "live_orders": False}
    diag_rel = None
    if diagnostics is not None:
        diag_rel = f"diagnostics/{did}.json"
        _write_once(runs / diag_rel, {"decision_id": did, "status": "DIAGNOSTIC_NOT_A_DECISION", **diagnostics,
                                      "simulated": True, "live_orders": False})
        full["diagnostic_artifact"] = diag_rel
    rel = f"decisions/{did}.json"
    if "generated_at" not in full:
        full["generated_at"] = now().isoformat()
    sha = _write_once(runs / rel, full)
    stored = json.loads((runs / rel).read_text(encoding="utf-8"))  # the first write wins for a re-used id
    from .research import explain
    entry = {"decision_id": did, "origin": origin, "day": stored["day"], "action": stored["action"],
             "reasons": list(stored.get("reasons", [])), "explanation": explain({"reasons": stored.get("reasons", [])}),
             "candidate": stored.get("candidate"), "h": stored.get("h"), "policy_digest": stored.get("policy_digest"),
             "promotion_id": stored.get("promotion_id"), "model_id": stored.get("model_id"),
             "symbols": list(stored.get("symbols", [])), "late_start": bool(stored.get("late_start", False)),
             "artifact": rel, "artifact_sha256": sha, "diagnostic_artifact": stored.get("diagnostic_artifact"),
             "simulated": True, "live_orders": False}
    db = Store(root / "evidence.sqlite3")
    try:
        db.append(KIND, f"marketlab:{origin}", stored["day"], entry)
    finally:
        db.close()
    return entry


def timeline(root: Path, limit: int = 30) -> list[dict]:
    """Newest first. Records written before decision ids existed are shown with ``decision_id`` None."""
    path = root / "evidence.sqlite3"
    if not path.exists():
        return []
    db = Store(path)
    try:
        rows = db.recent(KIND, limit)
    finally:
        db.close()
    out = []
    for r in rows:
        p = dict(r["payload"])
        p.setdefault("decision_id", None)
        p["recorded_at"] = r["received_at"]
        out.append(p)
    return out


def load(root: Path, decision_id: str, runs: Path | None = None) -> dict | None:
    """The full record for an id, checked against the hash in the timeline. None when unknown."""
    runs = runs or runs_dir(root)
    safe = "".join(ch for ch in decision_id if ch.isalnum() or ch in "-_")
    entry = next((e for e in timeline(root, 10_000) if e.get("decision_id") == safe), None)
    path = runs / "decisions" / f"{safe}.json"
    if entry is None or not path.exists():
        return None
    raw = path.read_bytes()
    rec = json.loads(raw)
    rec["integrity"] = "OK" if hashlib.sha256(raw).hexdigest() == entry.get("artifact_sha256") else "HASH_MISMATCH"
    rec["recorded_at"] = entry.get("recorded_at")
    return rec


def latest(root: Path, runs: Path | None = None) -> dict | None:
    for e in timeline(root, 50):
        if e.get("decision_id"):
            return load(root, e["decision_id"], runs)
    return None
