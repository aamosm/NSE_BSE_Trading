"""Run registry: the frozen holdout, immutable evaluation artifacts and promotion records (spec 5.2 gate 3, 8.1, 8.6).

* Holdout: ``runs/holdout.json`` is written once (``freeze_holdout``) and never moves. Its start date is a calendar
  cutoff: development runs read the panel only through a view ending the day before it, so appending or changing
  holdout prices cannot change any development decision, label, metric or hash.
* Artifacts: every evaluation writes a new file ``runs/eval/<trial_id>/<run_id>.json`` (development) or
  ``runs/holdout/<trial_id>/<run_id>.json`` (the single holdout evaluation); nothing is overwritten.
* Promotion: the only way a decision can become PAPER_PLAN. A record is written only after the full spec 8.6
  rule passed on a development run and the holdout run of the same trial. It is tied to the candidate, horizon,
  trial id, input manifest, the SHA-256 of both reports and the effective policy digest. Verification re-hashes
  every cited report and re-reads the criteria inside it; a hand-written or edited file, a command-line flag or a
  changed policy cannot pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date
from pathlib import Path

from ..common import atomic_json, now

PROMOTIONS = "promotions"
# Every spec 8.6 development criterion evaluate.promotion() writes (the holdout one is judged from the holdout
# report). A development report must carry ALL of them and each must be True: a report with fewer keys is
# incomplete, never "all passed" (audit finding 2026-11-07: a report carrying only holdout_net_positive passed).
REQUIRED_DEV_CRITERIA = ("verified_folds_exist", "net_positive_pooled", "folds_positive_60pct", "n_eff_ge_mintrl",
                         "dsr_95", "pbo_le_025", "coverage_80_in_band", "brier_skill_positive",
                         "stresses_net_positive", "no_year_or_stock_over_half", "attribution_available")
HOLDOUT_FILE = "holdout.json"
REQUIRED = ("promotion_id", "candidate", "h", "trial_id", "manifest_hash", "policy_digest", "development_report",
            "development_sha256", "holdout_report", "holdout_sha256", "verdict")


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


# ---- holdout ----------------------------------------------------------------------------------------------

def holdout_manifest(runs: Path) -> dict | None:
    p = runs / HOLDOUT_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def freeze_holdout(runs: Path, sessions: list[date], n_sessions: int = 250, note: str = "") -> dict:
    """Freeze the holdout start as the first of the last ``n_sessions`` exchange sessions now held. Idempotent: an
    existing manifest is returned unchanged (the holdout never moves when the panel grows)."""
    existing = holdout_manifest(runs)
    if existing:
        return existing
    if len(sessions) < n_sessions + 1:
        raise ValueError(f"HOLDOUT_TOO_EARLY: {len(sessions)} sessions held; freeze after the backfill")
    man = {"holdout_start": sessions[-n_sessions].isoformat(), "holdout_sessions_at_freeze": n_sessions,
           "frozen_at": now().isoformat(), "last_session_at_freeze": sessions[-1].isoformat(),
           "rule": "spec 8.1: the last sessions before the freeze are evaluated once, after everything else is final",
           "note": note}
    runs.mkdir(parents=True, exist_ok=True)
    tmp = runs / f".{HOLDOUT_FILE}.{uuid.uuid4().hex[:6]}"
    atomic_json(tmp, man)
    try:
        os.link(tmp, runs / HOLDOUT_FILE)  # create-if-absent
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)
    return holdout_manifest(runs)


# ---- immutable run artifacts -----------------------------------------------------------------------------

def write_run(runs: Path, report: dict) -> Path:
    kind = "holdout" if report.get("holdout") else "eval"
    folder = runs / kind / report["trial_id"]
    if kind == "holdout" and folder.exists() and any(folder.glob("*.json")):
        raise ValueError("HOLDOUT_ALREADY_EVALUATED: the holdout of this trial was opened before")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report['run_id']}.json"
    with open(path, "x", encoding="utf-8") as f:  # exclusive create: never overwrite
        json.dump(report, f, ensure_ascii=False, indent=1, allow_nan=False, default=str)
    return path


def run_id(trial_id: str, manifest_hash: str) -> str:
    return now().strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha256(f"{trial_id}|{manifest_hash}|{uuid.uuid4()}".encode()).hexdigest()[:8]


def development_reports(runs: Path) -> list[dict]:
    """Latest development report per trial id (the registered-trial record used for DSR and PBO)."""
    out = {}
    for p in sorted((runs / "eval").glob("*/*.json")):
        try:
            rep = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        rep["_path"] = str(p.relative_to(runs)).replace("\\", "/")
        out[rep.get("trial_id")] = rep
    return [v for k, v in sorted(out.items()) if k]


def holdout_runs(runs: Path, trial_id: str) -> list[Path]:
    return sorted((runs / "holdout" / trial_id).glob("*.json"))


# ---- promotion records -------------------------------------------------------------------------------------

def verify(runs: Path, record: dict) -> list[str]:
    """Problems with a promotion record (empty list = verified)."""
    problems = [f"MISSING_{k.upper()}" for k in REQUIRED if not record.get(k)]
    if problems:
        return problems
    if record["verdict"] != "PROMOTED":
        problems.append("VERDICT_NOT_PROMOTED")
    reps = {}
    for key in ("development", "holdout"):
        rel = record[f"{key}_report"]
        path = (runs / rel).resolve()
        if runs.resolve() not in path.parents:
            problems.append(f"{key.upper()}_REPORT_OUTSIDE_RUNS")
            continue
        if _sha(path) != record[f"{key}_sha256"]:
            problems.append(f"{key.upper()}_REPORT_HASH_MISMATCH")
            continue
        rep = json.loads(path.read_text(encoding="utf-8"))
        reps[key] = rep
        if rep.get("trial_id") != record["trial_id"] or not rep.get("manifest_hash"):
            problems.append(f"{key.upper()}_REPORT_IDENTITY_MISMATCH")
        cfg = rep.get("config") or {}
        if cfg.get("candidate") != record["candidate"] or cfg.get("h") != record["h"]:
            # audit finding 2026-11-07: an h = 20 report could back an h = 60 promotion
            problems.append(f"{key.upper()}_REPORT_CANDIDATE_OR_HORIZON_MISMATCH")
    dev, hold = reps.get("development"), reps.get("holdout")
    if dev is not None:
        crit = (dev.get("promotion") or {}).get("criteria") or {}
        missing = [k for k in REQUIRED_DEV_CRITERIA if k not in crit]
        if missing:
            problems.append("DEVELOPMENT_CRITERIA_MISSING:" + ",".join(missing))
        elif any(crit[k] is not True for k in REQUIRED_DEV_CRITERIA):
            problems.append("DEVELOPMENT_CRITERIA_NOT_ALL_PASSED")
        if dev.get("policy_digest") != record["policy_digest"] or dev.get("holdout") is not False:
            problems.append("DEVELOPMENT_REPORT_POLICY_OR_KIND_MISMATCH")
    if hold is not None:
        if not (hold.get("holdout") is True and (hold.get("net_rupees_total") or 0) > 0):
            problems.append("HOLDOUT_NOT_POSITIVE")
        if hold.get("policy_digest") != record["policy_digest"]:
            problems.append("HOLDOUT_REPORT_POLICY_MISMATCH")
    return problems


def write_promotion(runs: Path, dev_path: Path, holdout_path: Path, candidate: str, h: int) -> dict | None:
    """Write a promotion record when (and only when) it verifies. Returns the record or None."""
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    rec = {"promotion_id": f"{dev['trial_id']}-{uuid.uuid4().hex[:6]}", "candidate": candidate, "h": h,
           "trial_id": dev["trial_id"], "manifest_hash": dev["manifest_hash"], "policy_digest": dev["policy_digest"],
           "development_report": str(dev_path.relative_to(runs)).replace("\\", "/"), "development_sha256": _sha(dev_path),
           "holdout_report": str(holdout_path.relative_to(runs)).replace("\\", "/"), "holdout_sha256": _sha(holdout_path),
           "verdict": "PROMOTED", "written_at": now().isoformat()}
    if verify(runs, rec):
        return None
    atomic_json(runs / PROMOTIONS / f"{rec['promotion_id']}.json", rec)
    return rec


def verified_promotion(runs: Path, candidate: str, h: int, policy_digest: str) -> tuple[dict | None, list[str]]:
    """(record, problems). The record is returned only when it verifies for this candidate, horizon and policy."""
    folder = runs / PROMOTIONS
    if not folder.exists():
        return None, ["NO_PROMOTION_RECORD"]
    seen = []
    for p in sorted(folder.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            seen.append(f"UNREADABLE:{p.name}")
            continue
        if rec.get("candidate") != candidate or rec.get("h") != h:
            continue
        if rec.get("policy_digest") != policy_digest:
            seen.append("PROMOTION_POLICY_MISMATCH")
            continue
        problems = verify(runs, rec)
        if not problems:
            return rec, []
        seen.extend(problems)
    return None, seen or ["NO_PROMOTION_RECORD"]
