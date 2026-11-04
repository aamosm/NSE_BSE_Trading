from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .backtest import load_bars


def audit_dataset(path: Path):
    bars = load_bars(path)
    meta_path = path.with_suffix(".metadata.json")
    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    blockers = []
    if metadata.get("sha256") != digest:
        blockers.append("METADATA_MISSING_OR_CONTENT_HASH_MISMATCH")
    for key in ("corporate_actions_verified", "historical_universe_verified",
                "historical_security_status_verified", "historical_fee_schedule_verified"):
        if metadata.get(key) is not True:
            blockers.append(key.upper())
    jumps = [{"at": str(c.start), "close_change": float(c.close/b.close-1)}
             for b, c in zip(bars, bars[1:]) if abs(c.close/b.close-1) > .25]
    if jumps:
        blockers.append("LARGE_PRICE_JUMPS_NEED_REVIEW")
    zeros = sum(b.volume == 0 for b in bars)
    return {"sha256": digest, "bars": len(bars), "zero_volume_bars": zeros, "large_jumps": jumps,
            "blockers": blockers, "metadata_checks_passed": not blockers,
            "certified_for_trading": False,
            "note": "Metadata declarations require evidence and human review. This is not exchange-calendar validation."}
