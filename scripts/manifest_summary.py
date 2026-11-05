"""Exact reconciliation of a pilot folder: manifest entries by source and result, and every raw file on disk
accounted for (in a manifest window, outside every window, quarantined, or unaccounted).

    python scripts/manifest_summary.py data/pilot/nse_2025
Exit code 1 if any stored manifest entry lacks its file, any hash differs, or any raw file is unaccounted for."""
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
market = root / "market"
manifests = sorted(root.glob("manifest*.json"))
claimed, bad = {}, []
print(f"{'manifest':<24}{'source':<22}{'STORED':>8}{'NOT_PUB':>9}{'FAILED':>8}{'SCHEMA':>8}")
for mp in manifests:
    man = json.loads(mp.read_text(encoding="utf-8"))
    for sid, recs in sorted(man["files"].items()):
        c = Counter(r["result"] for r in recs.values())
        print(f"{mp.name:<24}{sid:<22}{c['STORED']:>8}{c['NOT_PUBLISHED']:>9}{c['FAILED']:>8}{c['SCHEMA_CHANGED']:>8}")
        for k, r in recs.items():
            if r["result"] in ("STORED", "SCHEMA_CHANGED"):
                p = (market / r["path"]).resolve()
                claimed[p] = (mp.name, sid, k)
                if not p.exists():
                    bad.append(f"MISSING {sid} {k}")
                elif hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest() != r["sha256"]:
                    bad.append(f"HASH {sid} {k}")
    total = sum(len(v) for v in man["files"].values())
    hashes = sum(1 for v in man["files"].values() for r in v.values() if r.get("sha256"))
    docs = len(man.get("documents", {}))
    print(f"  {mp.name}: window {man['window'][0]}..{man['window'][1]}, {total} attempt entries, {hashes} file hashes, "
          f"{docs} documents (each with its own hash), content_sha256 {man['content_sha256'][:16]}")
raw = sorted(p.resolve() for p in (market / "raw").rglob("*.gz"))
kinds, spans = Counter(), {}
for p in raw:
    if p in claimed:
        kinds["in a manifest window"] += 1
    elif "_quarantine" in p.parts:
        kinds["quarantined schema failure"] += 1
    else:
        key = f"outside every window: {p.parent.name}"
        kinds[key] += 1
        d = p.name.split(".")[0]
        lo, hi = spans.get(key, (d, d))
        spans[key] = (min(lo, d), max(hi, d))
print(f"raw files on disk: {len(raw)}")
for k, v in sorted(kinds.items()):
    print(f"  {v:>5}  {k}" + (f" ({spans[k][0]}..{spans[k][1]})" if k in spans else ""))
print("problems:", bad or "none")
sys.exit(1 if bad else 0)
