"""Parity of the legacy and UDiFF bhavcopies on the days NSE published both (early July 2024).

    python scripts/legacy_parity.py data/research

For every equity-series row present in both files of a day, compares open, high, low, close, previous close,
volume, traded value and trade count. Prints counts and the first mismatches; exits 1 on any mismatch, so a
lower-cost model can run it as a gate. Reads stored files only; no network.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from marketlab import history, sources  # noqa: E402
from marketlab.master import parse_bhavcopy, parse_legacy_bhavcopy  # noqa: E402
from marketlab.quant.panel import EQUITY_SERIES  # noqa: E402

FIELDS = ("OpnPric", "HghPric", "LwPric", "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main(root: Path) -> int:
    market = root / "market"
    res = history.bhavcopy_results(market)
    att = history.attempts(market)
    both = sorted(d for d in res if att.get("nse_bhavcopy", {}).get(d, {}).get("result") == "STORED"
                  and att.get("nse_bhavcopy_legacy", {}).get(d, {}).get("result") == "STORED")
    if not both:
        print("NO_OVERLAP_DAYS")
        return 1
    bad_total = 0
    for k in both:
        d = date.fromisoformat(k)
        new = {(r["ISIN"], r["SctySrs"]): r for r in parse_bhavcopy(sources.read_raw(market, "nse_bhavcopy", d), zipped=True)
               if r.get("SctySrs") in EQUITY_SERIES}
        old = {(r["ISIN"], r["SctySrs"]): r for r in parse_legacy_bhavcopy(sources.read_raw(market, "nse_bhavcopy_legacy", d))
               if r.get("SctySrs") in EQUITY_SERIES}
        common = set(new) & set(old)
        bad = []
        for key in sorted(common):
            for f in FIELDS:
                a, b = num(new[key].get(f)), num(old[key].get(f))
                tol = 0.51 if f == "TtlTrfVal" else 1e-6  # traded value: rounding to the rupee in one format
                if a is None or b is None or abs(a - b) > tol * max(1.0, 1e-9 * abs(a)):
                    bad.append((key, f, a, b))
        bad_total += len(bad)
        print(f"{k}: UDiFF {len(new)} rows, legacy {len(old)} rows, common {len(common)}, "
              f"only-UDiFF {len(set(new) - set(old))}, only-legacy {len(set(old) - set(new))}, field mismatches {len(bad)}")
        for b in bad[:5]:
            print("   ", b)
    print("PARITY_OK" if bad_total == 0 else f"PARITY_FAILED {bad_total}")
    return 0 if bad_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/research")))
