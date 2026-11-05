"""Which code is this process running? (served by /health and /api/version)

A browser check proves something only if it names the code behind it. This reports the source folder actually
imported, the git commit and dirty state of that folder, and a digest of every ``.py`` file under it, both as
loaded at process start and now (a changed digest means the running process is older than the files on disk).
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
STARTED_AT = datetime.now(timezone.utc).isoformat()


def source_digest() -> str:
    h = hashlib.sha256()
    for p in sorted(PACKAGE.rglob("*.py")):
        h.update(p.relative_to(PACKAGE).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _git(*args) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=PACKAGE, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


DIGEST_AT_START = source_digest()
GIT_AT_START = {"head": _git("rev-parse", "HEAD"), "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "toplevel": _git("rev-parse", "--show-toplevel")}


def build_info() -> dict:
    now = source_digest()
    dirty = _git("status", "--porcelain", "--", ".")
    return {"code_path": str(PACKAGE), "git_head": GIT_AT_START["head"], "git_branch": GIT_AT_START["branch"],
            "git_toplevel": GIT_AT_START["toplevel"], "git_head_now": _git("rev-parse", "HEAD"),
            "package_dirty_paths": len(dirty.splitlines()) if dirty else 0,
            "source_digest_at_start": DIGEST_AT_START, "source_digest_now": now,
            "source_changed_since_start": now != DIGEST_AT_START, "process_started_at": STARTED_AT,
            "pid": os.getpid(), "python": platform.python_version()}
