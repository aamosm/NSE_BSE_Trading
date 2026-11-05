"""Integer, fixed-cost-aware allocation and the EXIT.v1 policy (spec section 5).

Objective over quantities q_i (V_i = q_i P_i):
    sum_i [(mu_i - c_v - s_in - s_out) V_i - F 1[q_i>0]] - gamma/2 sum_ij V_i V_j sigma_i sigma_j rho_ij
subject to cash after buy fees, per-stock cap, position count K, long-only integers. Exact enumeration for small
instances; otherwise continuous optimum per subset then integer neighbourhood search with exact feasibility.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from decimal import Decimal

from ..costs import charges

VARIABLE_ROUND_TRIP = 0.00222481  # NSE delivery, both sides, excluding rupee rounding and DP (spec section 0)
BUY_VARIABLE = 0.00118741
FIXED_SELL = 15.34  # DP charge per ISIN per delivery sell day


@dataclass(frozen=True, slots=True)
class Candidate:
    isin: str
    price: float
    mu: float  # shrunk mean gross excess return over the horizon (fraction)
    sigma: float  # forecast scale over the horizon (fraction)
    slippage: float = 0.002  # s_in + s_out
    q10: float = float("nan")
    symbol: str = ""
    sector: str | None = None


@dataclass(frozen=True, slots=True)
class Policy:
    W: float
    reserve_fraction: float = 0.20
    cap_fraction: float = 0.50
    K: int = 2
    gamma: float | None = None  # default 2/W (half-Kelly)
    min_edge: float = 0.001  # m_min, spec 5.2 gate 4
    tail_limit: float = 0.08  # L, spec 5.2 gate 5
    sector_cap_fraction: float = 0.60
    hysteresis_rupees: float = 5.0

    def risk_aversion(self) -> float:
        return self.gamma if self.gamma is not None else 2.0 / self.W

    @staticmethod
    def for_capital(W: float) -> "Policy":
        if W <= 25_000:
            return Policy(W, K=2, cap_fraction=0.50)
        if W <= 200_000:
            return Policy(W, K=4, cap_fraction=0.35)
        return Policy(W, K=10, cap_fraction=0.20)

    @staticmethod
    def from_owner(saved: dict) -> "Policy":
        """The effective policy for the owner's saved settings: K and the per-stock cap default to the spec 5.4 tier
        for the capital when not set (None); the risk multiplier m gives gamma = 2 / (m W) (spec 5.1)."""
        W = float(saved["capital"])
        tier = Policy.for_capital(W)
        m = float(saved.get("risk_multiplier") or 1.0)
        K = tier.K if saved.get("K") is None else int(saved["K"])
        cap = tier.cap_fraction if saved.get("cap_fraction") is None else float(saved["cap_fraction"])
        reserve = 0.20 if saved.get("reserve_fraction") is None else float(saved["reserve_fraction"])
        return Policy(W, reserve_fraction=reserve, cap_fraction=cap, K=K, gamma=2.0 / (m * W))

    def to_json(self) -> dict:
        return {"W": self.W, "reserve_fraction": self.reserve_fraction, "cap_fraction": self.cap_fraction, "K": self.K,
                "gamma": self.risk_aversion(), "min_edge": self.min_edge, "tail_limit": self.tail_limit,
                "sector_cap_fraction": self.sector_cap_fraction, "hysteresis_rupees": self.hysteresis_rupees,
                "cap_rupees": round(self.cap_fraction * self.W, 2), "reserve_rupees": round(self.reserve_fraction * self.W, 2)}

    def digest(self) -> str:
        import hashlib
        import json
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()[:12]


def break_even(value: float) -> float:
    """Round-trip cost as a fraction of position value: 0.2225% + 15.34 / V."""
    return VARIABLE_ROUND_TRIP + FIXED_SELL / value if value > 0 else float("inf")


def entry_gate(c: Candidate, policy: Policy) -> tuple[bool, list[str]]:
    """Gates 4 and 5 of spec 5.2 (the others are checked by the caller: coverage, calibration, promotion,
    exchange rules, account freshness). Returns (ok, reasons)."""
    reasons = []
    best = min(policy.cap_fraction * policy.W, policy.W * (1 - policy.reserve_fraction))  # largest feasible position
    if c.price > best:
        reasons.append("PRICE_ABOVE_CAP")
    if c.mu - break_even(best) - c.slippage < policy.min_edge:
        reasons.append("EDGE_BELOW_COST")
    if not math.isnan(c.q10) and c.q10 - break_even(best) - c.slippage < -policy.tail_limit:
        reasons.append("TAIL_LIMIT")
    return (not reasons), reasons


def objective(values: list[float], cands: list[Candidate], corr: list[list[float]], policy: Policy) -> float:
    g = policy.risk_aversion()
    ret = 0.0
    for v, c in zip(values, cands):
        if v > 0:
            ret += (c.mu - VARIABLE_ROUND_TRIP - c.slippage) * v - FIXED_SELL
    var = 0.0
    for i, (vi, ci) in enumerate(zip(values, cands)):
        if vi == 0:
            continue
        for j, (vj, cj) in enumerate(zip(values, cands)):
            if vj:
                var += vi * vj * ci.sigma * cj.sigma * corr[i][j]
    return ret - g / 2 * var


def feasible(qs: list[int], cands: list[Candidate], policy: Policy, cash_available: float) -> bool:
    cap = policy.cap_fraction * policy.W
    held = 0
    spend = 0.0
    sectors: dict[str, float] = {}
    for q, c in zip(qs, cands):
        if q <= 0:
            continue
        v = q * c.price
        if v > cap + 1e-9:
            return False
        held += 1
        spend += v * (1 + BUY_VARIABLE)
        if c.sector:
            sectors[c.sector] = sectors.get(c.sector, 0.0) + v
    if held > policy.K or spend > cash_available + 1e-9:
        return False
    return all(v <= policy.sector_cap_fraction * policy.W + 1e-9 for v in sectors.values())


def exact_charges_feasible(qs: list[int], cands: list[Candidate], cash_available: float) -> bool:
    """Recompute buy-side charges with the cited fee schedule (rupee-rounded STT) before accepting a plan."""
    total = Decimal("0")
    for q, c in zip(qs, cands):
        if q > 0:
            v = Decimal(str(round(q * c.price, 2)))
            total += v + sum(charges(v, side="BUY", style="delivery").values(), Decimal("0"))
    return float(total) <= cash_available + 1e-6


def _continuous_subset(idx: list[int], cands, corr, policy, cash_available) -> list[float]:
    """Projected coordinate ascent on V for one subset (concave quadratic, box + budget)."""
    g = policy.risk_aversion()
    cap = policy.cap_fraction * policy.W
    V = [0.0] * len(idx)
    for _ in range(50):
        changed = False
        for a, i in enumerate(idx):
            ci = cands[i]
            e = ci.mu - VARIABLE_ROUND_TRIP - ci.slippage
            cross = sum(V[b] * cands[j].sigma * corr[i][j] for b, j in enumerate(idx) if b != a)
            v = (e / g - ci.sigma * cross) / (ci.sigma ** 2) if ci.sigma > 0 else 0.0
            v = max(0.0, min(cap, v))
            if abs(v - V[a]) > 1e-6:
                V[a] = v
                changed = True
        total = sum(V) * (1 + BUY_VARIABLE)
        if total > cash_available:
            V = [v * cash_available / total for v in V]
        if not changed:
            break
    return V


def plan(cands: list[Candidate], corr: list[list[float]], policy: Policy, cash_available: float, *,
         enumerate_limit: int = 60_000) -> dict:
    """Choose integer quantities. Candidates should already pass gates 1-3, 6, 7; gates 4-5 are applied here."""
    passing = [c for c in cands if entry_gate(c, policy)[0]]
    rejected = {c.isin: entry_gate(c, policy)[1] for c in cands if not entry_gate(c, policy)[0]}
    if not passing:
        return {"quantities": {}, "objective": 0.0, "rejected": rejected, "method": "none", "note": "no candidate passes the gate"}
    order = sorted(range(len(cands)), key=lambda i: -(cands[i].mu - VARIABLE_ROUND_TRIP - cands[i].slippage))
    pool = [i for i in order if cands[i] in passing][:10]
    cap = policy.cap_fraction * policy.W
    best = (0.0, [0] * len(cands), "cash")
    for size in range(1, min(policy.K, len(pool)) + 1):
        for subset in itertools.combinations(pool, size):
            ranges = [range(1, int(cap // cands[i].price) + 1) for i in subset]
            combos = 1
            for r in ranges:
                combos *= max(1, len(r))
            qs = [0] * len(cands)
            if combos <= enumerate_limit:
                for pick in itertools.product(*ranges):
                    for i, q in zip(subset, pick):
                        qs[i] = q
                    if feasible(qs, cands, policy, cash_available):
                        val = objective([q * c.price for q, c in zip(qs, cands)], cands, corr, policy)
                        if val > best[0]:
                            best = (val, qs[:], "enumeration")
                    for i in subset:
                        qs[i] = 0
            else:
                V = _continuous_subset(list(subset), cands, corr, policy, cash_available)
                centers = [int(round(v / cands[i].price)) for v, i in zip(V, subset)]
                neigh = [range(max(1, c0 - 2), c0 + 3) for c0 in centers]
                for pick in itertools.product(*neigh):
                    for i, q in zip(subset, pick):
                        qs[i] = q
                    if feasible(qs, cands, policy, cash_available):
                        val = objective([q * c.price for q, c in zip(qs, cands)], cands, corr, policy)
                        if val > best[0]:
                            best = (val, qs[:], "neighbourhood")
                    for i in subset:
                        qs[i] = 0
    val, qs, method = best
    if method != "cash" and not exact_charges_feasible(qs, cands, cash_available):
        # exact rupee-rounded charges exceeded the linear estimate: shave one share off the largest position
        i = max(range(len(qs)), key=lambda k: qs[k] * cands[k].price)
        qs[i] -= 1
        val = objective([q * c.price for q, c in zip(qs, cands)], cands, corr, policy) if any(qs) else 0.0
        method += "+repair"
    return {"quantities": {cands[i].isin: q for i, q in enumerate(qs) if q > 0}, "objective": val,
            "values": {cands[i].isin: round(q * cands[i].price, 2) for i, q in enumerate(qs) if q > 0},
            "rejected": rejected, "method": method}


# ---- EXIT.v1 ----------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Position:
    isin: str
    value: float  # current market value
    mu_cont: float  # shrunk mean for holding one more horizon
    sigma: float
    entry_q10: float = float("nan")
    realized: float = float("nan")  # return since entry
    sessions_held: int = 0
    h: int = 20


def exit_decision(pos: Position, alternatives: list[Candidate], policy: Policy, *, flags: tuple[str, ...] = ()) -> dict:
    """Spec 5.5. Returns action HOLD/EXIT with the utilities compared and the triggers that fired."""
    g = policy.risk_aversion()
    triggers = [f for f in flags]
    if not math.isnan(pos.realized) and not math.isnan(pos.entry_q10) and pos.realized < pos.entry_q10:
        triggers.append("BELOW_ENTRY_Q10")
    expired = pos.sessions_held >= pos.h
    if not expired and not triggers:
        return {"action": "HOLD", "reason": "WITHIN_HORIZON", "triggers": []}
    u_hold = pos.value * pos.mu_cont - g / 2 * pos.value ** 2 * pos.sigma ** 2
    best_alt, u_alt = None, 0.0
    for c in alternatives:
        u = pos.value * (c.mu - VARIABLE_ROUND_TRIP - c.slippage) - FIXED_SELL - g / 2 * pos.value ** 2 * c.sigma ** 2
        if u > u_alt:
            best_alt, u_alt = c.isin, u
    hold = u_hold >= max(0.0, u_alt) - policy.hysteresis_rupees
    return {"action": "HOLD" if hold else "EXIT", "u_hold": round(u_hold, 4), "u_alt": round(u_alt, 4),
            "best_alternative": best_alt, "triggers": triggers, "reason": "EXPIRY_REVIEW" if expired else "TRIGGER_REVIEW"}
