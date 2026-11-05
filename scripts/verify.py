"""Reproducible verification of this checkout: proves which code ran, runs the test suites, records the result.

    .venv\\Scripts\\python.exe scripts\\verify.py            # targeted suites (integrity, replay, pilot, dashboard)
    .venv\\Scripts\\python.exe scripts\\verify.py --all      # every test file
    scripts\\verify.cmd [--all]                              # same, from cmd or PowerShell

It refuses to run when ``marketlab`` would be imported from anywhere but this checkout's ``src`` (an editable install
of another checkout, a stale PYTHONPATH). The result is written once to data/runs/verify/<head>-<utc>.json with the
interpreter, git HEAD, dirty files, per-file pass/fail counts and the pilot manifest re-hash. Exit code 0 only when
every selected test passed and the manifest (if present) verifies.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETED = ["test_decision_integrity.py", "test_replay_correctness.py", "test_history_pilot.py", "test_quant_pipeline.py",
            "test_quant_core.py", "test_paper_ledger.py", "test_corporate_action_registry.py", "test_service.py",
            "test_webapp.py", "test_webapp_ui.py", "test_boundaries.py"]


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    import marketlab
    origin = Path(marketlab.__file__).resolve()
    if ROOT / "src" not in origin.parents:
        print(f"REFUSED: marketlab imports from {origin}, not from {ROOT / 'src'}")
        return 2
    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py")) if "--all" in sys.argv else \
        [f for f in TARGETED if (ROOT / "tests" / f).exists()]
    head, branch = git("rev-parse", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = [line for line in git("status", "--porcelain").splitlines() if line]
    print(f"python   {sys.executable} ({platform.python_version()})")
    print(f"code     {origin.parent}")
    print(f"git      {branch} {head[:12]}{' DIRTY (' + str(len(dirty)) + ' paths)' if dirty else ' clean'}")
    xml = Path(tempfile.mkdtemp()) / "junit.xml"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
                           *[str(ROOT / "tests" / f) for f in files]], cwd=ROOT, env=env, capture_output=True, text=True)
    per_file, failures = {}, []
    if xml.exists():
        for case in ET.parse(xml).getroot().iter("testcase"):
            f = (case.get("classname") or "").split(".")[-1] + ".py"
            row = per_file.setdefault(f, {"passed": 0, "failed": 0, "skipped": 0})
            if case.find("failure") is not None or case.find("error") is not None:
                row["failed"] += 1
                failures.append(f"{f}::{case.get('name')}")
            elif case.find("skipped") is not None:
                row["skipped"] += 1
            else:
                row["passed"] += 1
    manifest = None
    man_path = ROOT / "data" / "pilot" / "nse_2025" / "manifest.json"
    if man_path.exists():
        from marketlab import history
        man = json.loads(man_path.read_text(encoding="utf-8"))
        manifest = {"path": str(man_path.relative_to(ROOT)), "content_sha256": man.get("content_sha256"),
                    "problems": history.verify_manifest(man_path.parent / "market", man)}
    totals = {k: sum(r[k] for r in per_file.values()) for k in ("passed", "failed", "skipped")}
    ok = proc.returncode == 0 and totals["failed"] == 0 and totals["passed"] > 0 and not (manifest and manifest["problems"])
    for f in files:
        r = per_file.get(f, {"passed": 0, "failed": 0, "skipped": 0})
        print(f"  {'PASS' if r['failed'] == 0 and r['passed'] else 'FAIL'}  {f:<38} {r['passed']} passed, {r['failed']} failed")
    if manifest:
        print(f"manifest {manifest['path']}: {'verified' if not manifest['problems'] else manifest['problems'][:5]}")
    if not xml.exists():
        print(proc.stdout[-3000:], proc.stderr[-3000:])
    result = {"verified_at": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
              "python_version": platform.python_version(), "code": str(origin.parent), "git_head": head, "branch": branch,
              "dirty_paths": dirty, "suites": files, "per_file": per_file, "totals": totals, "failures": failures,
              "pytest_exit": proc.returncode, "manifest": manifest, "result": "PASS" if ok else "FAIL"}
    out = ROOT / "data" / "runs" / "verify" / f"{head[:12] or 'nogit'}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print(f"{result['result']}: {totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped -> {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
