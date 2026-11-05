"""Acquire the bounded NSE pilot (official archives, one attempt per file per date, 1.5 s apart).

    python scripts/pilot_acquire.py data/pilot/nse_2025 2025-01-01 2025-07-31
Also fetches the format-transition files (legacy and UDiFF bhavcopy, 3-8 Jul 2024)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from marketlab import history, sources  # noqa: E402

root = Path(sys.argv[1])
start, end = date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3])
market = root / "market"
for d in (date(2024, 7, 3), date(2024, 7, 4), date(2024, 7, 5), date(2024, 7, 8)):
    print("transition", d, [(r["source"], r["result"]) for r in sources.collect(market, d, ["nse_bhavcopy", "nse_bhavcopy_legacy"])],
          flush=True)
print("window", history.acquire(market, start, end, progress=lambda m: print(m, flush=True)), flush=True)
