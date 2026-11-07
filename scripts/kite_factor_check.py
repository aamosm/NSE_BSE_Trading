"""Independent verification of every split/bonus factor in the corporate-action registry with Kite's adjusted candles.

    python scripts/kite_factor_check.py data/research

Zerodha adjusts its historical candles for splits and bonuses; the panel holds the exchange's actual prices. For an
action with factor f (new price ~ old price x f, e.g. 0.1 for a 1:10 split), Kite scales every earlier price by f,
so across the ex-date t (previous session p):

    step = (exchange_close[p] / kite_close[p]) / (exchange_close[t] / kite_close[t])  ==  1 / f

A second, independent provider thus confirms or refutes each factor the registry applies to features and labels.
Reads stored files only (no network). Prints counts and the disagreements; exits 1 on any disagreement.
"""
import glob
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from marketlab import action_registry  # noqa: E402
from marketlab.quant.panel import Panel  # noqa: E402

TOL = 0.01


def kite_closes(kite: Path, token: int) -> dict:
    out = {}
    for f in glob.glob(str(kite / "day" / str(token) / "*.json")):
        for c in json.load(open(f, encoding="utf-8"))["candles"]:
            out[date.fromisoformat(c[0][:10])] = float(c[4])
    return out


def main(root: Path) -> int:
    market = root / "market"
    kite = market / "kite"
    sel = sorted(glob.glob(str(kite / "instruments" / "selected-*.json")))[-1]
    tok = {i["symbol"]: i["token"] for i in json.load(open(sel, encoding="utf-8"))["instruments"] if i["segment"] == "NSE"}
    pn = Panel(market / "panel.sqlite3")
    idx = action_registry.load_index(market, pn)
    sessions = pn.sessions()
    pos = {d: i for i, d in enumerate(sessions)}
    cache, stats, bad = {}, Counter(), []
    for (isin, ex), la in sorted(idx.by_key.items(), key=lambda kv: kv[0][1]):
        if la.status != "RATIO_CONSISTENT" or not la.price_factor or ex not in pos or pos[ex] == 0:
            continue
        stats["actions"] += 1
        p = sessions[pos[ex] - 1]
        before = pn.bars(isin)
        bp = next((b for b in before if b.day == p), None)
        after_isin = la.successor_isin or isin
        bt = next((b for b in pn.bars(after_isin) if b.day == ex), None)
        if bp is None or bt is None:
            stats["no_exchange_bar"] += 1
            continue
        latest = pn.bars(after_isin)[-1].symbol if pn.bars(after_isin) else bt.symbol
        token = tok.get(bt.symbol) or tok.get(latest)
        if token is None:
            stats["no_kite_token (delisted or renamed)"] += 1
            continue
        if token not in cache:
            cache[token] = kite_closes(kite, token)
        kc = cache[token]
        if p not in kc or ex not in kc:
            stats["no_kite_candle_on_the_days"] += 1
            continue
        step = (bp.close / kc[p]) / (bt.close / kc[ex])
        want = 1 / la.price_factor
        if abs(step / want - 1) <= TOL:
            stats["agree"] += 1
        else:
            stats["disagree"] += 1
            bad.append({"symbol": bt.symbol, "ex": ex.isoformat(), "registry_factor": round(la.price_factor, 6),
                        "kite_implied_factor": round(1 / step, 6), "kinds": la.kinds})
    pn.close()
    for k, v in stats.most_common():
        print(f"  {k:40s} {v}")
    for b in bad[:25]:
        print("  DISAGREE", b)
    checked = stats["agree"] + stats["disagree"]
    print(f"KITE_FACTOR_CHECK {'OK' if not bad else 'DISAGREEMENTS'}: {stats['agree']} of {checked} checkable actions agree within {TOL:.0%}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/research")))
