from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
D = Decimal


def timestamp(value: str | datetime) -> datetime:
    t = datetime.fromisoformat(value) if isinstance(value, str) else value
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("An explicit timezone is required")
    return t.astimezone(IST)


def now() -> datetime:
    return datetime.now(IST)


def money(value) -> Decimal:
    x = D(str(value))
    if not x.is_finite():
        raise ValueError("Money must be finite")
    return x.quantize(D(".01"), rounding=ROUND_HALF_UP)


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
