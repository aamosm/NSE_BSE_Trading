"""Backfill the official NSE legacy-format bhavcopies (pre-UDiFF, before 8 Jul 2024) for the historical universe.

    python scripts/legacy_acquire.py data/research 2016-01-01 2024-07-02 [--daily 2026-11-06] [--source nse_indices_close]

Why: the backtest needs years of history, and the exchange bhavcopy is the only source that lists every security
that traded on each date, delisted ones included (Kite's instrument dump lists only today's survivors).

Rules it keeps (CLAUDE.md): official archive host only (nsearchives.nseindia.com), one attempt per file per date
through the registered collector (already-stored files are skipped; refusals are recorded, never retried in a
loop), 1.5 s between requests, weekdays only (a rare special Saturday/Sunday session is missed and noted).
``--daily D`` first collects every daily source for session D (the normal evening acquisition). ``--source S``
backfills another registered dated source instead (e.g. nse_indices_close: the benchmark levels every label needs).
Files land under <root>/market/raw/ (git-ignored; not redistributed). Prints counts only.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from marketlab import history, sources  # noqa: E402


def main(argv):
    flags = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1].startswith("--"))]
    source = flags.get("--source", "nse_bhavcopy_legacy")
    root, start, end = Path(args[0]), date.fromisoformat(args[1]), date.fromisoformat(args[2])
    market = root / "market"
    if "--daily" in flags:
        day = date.fromisoformat(flags["--daily"])
        print("daily", day, history.acquire(market, day, day, progress=None), flush=True)
    counts: dict[str, int] = {}
    d = start
    while d <= end:
        if d.weekday() < 5:
            for r in sources.collect(market, d, [source]):
                counts[r["result"]] = counts.get(r["result"], 0) + 1
        if d.day == 1:
            print(d, counts, flush=True)
        d += timedelta(days=1)
    print("backfill done", source, start, end, counts, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
