"""Promotion records: the only way a decision can become PAPER_PLAN (spec 5.2 gate 3, 8.6).

A promotion is written by the evaluator after the full spec 8.6 rule passed on the development folds and the
single holdout evaluation. It is tied to the candidate, horizon, trial configuration, input manifest, the
SHA-256 of the development and holdout reports it cites, and the effective policy digest. Verification re-hashes
every cited report and re-reads the verdict inside it; a hand-written or edited file, a command-line flag or a
changed policy cannot pass. Records live in ``runs/promotions``; there is no other source.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROMOTIONS = "promotions"
REQUIRED = ("promotion_id", "candidate", "h", "trial_id", "manifest_hash", "policy_digest", "development_report",
            "development_sha256", "holdout_report", "holdout_sha256", "verdict")


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def verify(runs: Path, record: dict) -> list[str]:
    """Problems with a promotion record (empty list = verified)."""
    problems = [f"MISSING_{k.upper()}" for k in REQUIRED if not record.get(k)]
    if problems:
        return problems
    if record["verdict"] != "PROMOTED":
        problems.append("VERDICT_NOT_PROMOTED")
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
        if rep.get("trial_id") != record["trial_id"] or rep.get("manifest_hash") is None:
            problems.append(f"{key.upper()}_REPORT_IDENTITY_MISMATCH")
        if key == "holdout" and not (rep.get("holdout") is True and (rep.get("net_rupees_total") or 0) > 0):
            problems.append("HOLDOUT_NOT_POSITIVE")
        if key == "development" and (rep.get("promotion") or {}).get("verdict") != "PROMOTED":
            problems.append("DEVELOPMENT_VERDICT_NOT_PROMOTED")
    return problems


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
