"""Independent reproduction of every number on a ranking's stock cards (owner's test design, stage 1).

    python scripts/independent_check.py data/research [SYMBOL]

Imports NOTHING from marketlab: it reads the ranking file as plain JSON and recomputes each card from first
principles, so a bug in the app cannot hide by being copied into the check. Rates are Zerodha's published equity
delivery charges (https://zerodha.com/charges/, read 2026-11-07): brokerage 0; STT 0.1% each side (rounded to the
rupee, as on contract notes); NSE transaction 0.00307%; SEBI Rs 10 per crore; GST 18% on brokerage + SEBI +
transaction; stamp 0.015% on the buy side; DP Rs 15.34 per scrip on the sell day (GST included).

Checks per forecast card: raw forecast = intercept + sum(beta x rank); its market and stock parts; the shrunk forecast
from each part's own standard error, capped by the out-of-sample slope; whole shares under the cap; charges; cost
fraction with the liquidity-tier slippage; both gates; the tail threshold; the class. Prints counts per check, a
step-by-step walkthrough for SYMBOL, and exits 1 on any mismatch.
"""
import glob
import json
import math
import os
import sys
from collections import Counter

STT, NSE_TXN, SEBI_PER_CRORE, GST, STAMP_BUY, DP = 0.001, 0.0000307, 10.0, 0.18, 0.00015, 15.34
TIERS = ((10e7, 0.0010), (5e7, 0.0025), (1e7, 0.0050), (25e5, 0.0100), (0.0, 0.0200))  # per side, erratum E21


def paisa(x):
    return math.floor(x * 100 + 0.5) / 100


def side_charges(value, buy):
    stt = math.floor(value * STT + 0.5)  # rupee-rounded
    txn = value * NSE_TXN
    sebi = value * SEBI_PER_CRORE / 1e7
    gst = (txn + sebi) * GST
    stamp = value * STAMP_BUY if buy else 0.0
    return stt + paisa(txn) + paisa(sebi) + paisa(gst) + paisa(stamp) + (0.0 if buy else DP)


def slippage_side(median_value):
    for floor, s in TIERS:
        if (median_value or 0.0) >= floor:
            return s
    return TIERS[-1][1]


def latest(root):
    files = sorted(glob.glob(os.path.join(root, "runs", "rankings", "*", "*.json")), key=os.path.getmtime)
    return json.load(open(files[-1], encoding="utf-8")), files[-1]


def check_card(c, r, out):
    m, pol = r["model"], r["policy"]
    beta, feats = m["beta"], m["features"]
    market = [f for f in feats if f.startswith("mkt_") or f.startswith("breadth")]
    fc, x, costs, gates = c["forecast"], c["x"], c["costs"], c["gates"]
    mu = beta[0] + sum(b * x[f] for b, f in zip(beta[1:], feats))
    common = beta[0] + sum(b * x[f] for b, f in zip(beta[1:], feats) if f in market)
    steps = {"raw forecast": (mu, fc["mu_hat"], 2e-6), "market part": (common, fc["mu_common"], 2e-6),
             "stock part": (mu - common, fc["mu_specific"], 2e-6)}
    tau = fc["tau"]
    f_c = tau * tau / (tau * tau + fc["se_common"] ** 2)
    f_s = tau * tau / (tau * tau + fc["se_specific"] ** 2)
    if fc.get("calibration_slope") is not None:
        f_s = min(f_s, max(0.0, min(1.0, fc["calibration_slope"])))
    shrunk = f_c * fc["mu_common"] + f_s * fc["mu_specific"]
    steps["shrunk forecast"] = (shrunk, fc["mu_shrunk"], 3e-6)
    W = pol["W"]
    cap = min(pol["cap_fraction"] * W, W * (1 - pol["reserve_fraction"]))
    q = int(cap // c["close"]) if c["close"] > 0 else 0
    steps["whole shares"] = (q, costs["q"], 0)
    qc = q if q > 0 else 1
    value = paisa(qc * c["close"])
    ch = side_charges(value, True) + side_charges(value, False)
    steps["charges"] = (ch, costs["charges"], 0.03)
    slip = 2 * slippage_side(c.get("median_value_20"))
    cost = ch / value + slip
    steps["cost fraction"] = (cost, costs["cost_fraction"], 2e-6)
    q10 = fc["q10_abs"] if fc.get("q10_abs") is not None else fc["q10"]
    edge_fail = shrunk - cost < pol["min_edge"]
    tail_fail = (value / W) * (q10 - cost) < -pol["tail_limit"]
    app_edge_fail = "EDGE_BELOW_COST_AT_QUANTITY" in gates["at_quantity"]
    app_tail_fail = "TAIL_LIMIT_AT_QUANTITY" in gates["at_quantity"]
    steps["edge gate"] = (edge_fail, app_edge_fail, 0)
    steps["tail gate"] = (tail_fail, app_tail_fail, 0)
    thr = cost - pol["tail_limit"] * W / value
    if c.get("flip", {}).get("tail_q10_threshold") is not None:
        steps["tail threshold"] = (thr, c["flip"]["tail_q10_threshold"], 3e-6)
    thr_edge = cost + pol["min_edge"]
    if q == 0:
        want = "AVOID" if shrunk <= -thr_edge else "HOLD_OFF"
    elif c.get("allocation", {}).get("selected"):
        want = "BUY_CANDIDATE"
    elif not edge_fail and not tail_fail:
        want = "QUALIFIES"
    elif shrunk <= -thr_edge:
        want = "AVOID"
    elif tail_fail:
        want = "HIGH_RISK"
    else:
        want = "HOLD_OFF"
    steps["class"] = (want, c["class"], 0)
    for name, (mine, app, tol) in steps.items():
        ok = (mine == app) if tol == 0 else (app is not None and abs(mine - app) <= tol)
        out[name][ok] += 1
        if not ok:
            out["_bad"].append((c["symbol"], name, mine, app))
    return steps, {"f_c": f_c, "f_s": f_s, "value": value, "slip": slip, "q10": q10, "thr": thr}


def main(root, symbol=None):
    r, path = latest(root)
    out = {k: Counter() for k in ("raw forecast", "market part", "stock part", "shrunk forecast", "whole shares", "charges",
                                  "cost fraction", "edge gate", "tail gate", "tail threshold", "class")}
    out["_bad"] = []
    detail = None
    for c in r["stocks"]:
        if "forecast" not in c or "x" not in c:
            continue
        steps, extra = check_card(c, r, out)
        if symbol and c["symbol"] == symbol:
            detail = (c, steps, extra)
    print(f"ranking {os.path.basename(path)} for {r['day']} (created {r.get('created_at', '')[:19]})")
    for k, v in out.items():
        if k != "_bad":
            print(f"  {k:16s} agree {v[True]:5d}   disagree {v[False]:3d}")
    for b in out["_bad"][:10]:
        print("  MISMATCH", b)
    if detail:
        c, steps, e = detail
        fc = c["forecast"]
        print(f"\n{c['symbol']}: close {c['close']}, median traded value Rs {c.get('median_value_20') or 0:,.0f}")
        print(f"  raw {fc['mu_hat']:+.4%} = market {fc['mu_common']:+.4%} + stock {fc['mu_specific']:+.4%}")
        print(f"  keep {e['f_c']:.3f} of market (se {fc['se_common']:.4%}) and {e['f_s']:.3f} of stock (se "
              f"{fc['se_specific']:.4%}, slope cap {fc.get('calibration_slope')}) -> shrunk {steps['shrunk forecast'][0]:+.4%}")
        print(f"  {steps['whole shares'][0]} shares, value Rs {e['value']:,.2f}; charges Rs {steps['charges'][0]:.2f}; "
              f"slippage {e['slip']:.2%} round trip -> cost {steps['cost fraction'][0]:.4%}")
        print(f"  edge: {steps['shrunk forecast'][0]:+.4%} - {steps['cost fraction'][0]:.4%} vs min "
              f"{r['policy']['min_edge']:.2%} -> {'FAIL' if steps['edge gate'][0] else 'pass'}; tail: own-return q10 "
              f"{e['q10']:+.2%} must be >= {e['thr']:+.2%} -> {'FAIL' if steps['tail gate'][0] else 'pass'}; "
              f"class {steps['class'][0]} (app: {c['class']})")
    return 1 if out["_bad"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/research", sys.argv[2] if len(sys.argv) > 2 else None))
