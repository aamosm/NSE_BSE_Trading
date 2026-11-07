"""Integer, fixed-cost-aware allocation and the EXIT.v1 policy (spec section 5).

Objective over quantities q_i (V_i = q_i P_i):
    sum_i [(mu_i - c_v - s_in - s_out) V_i - F 1[q_i>0]] - gamma/2 sum_ij V_i V_j sigma_i sigma_j rho_ij
subject to cash after buy fees, per-stock cap, position count K, long-only integers. Exact enumeration for small
instances; otherwise continuous optimum per subset then integer neighbourhood search with exact feasibility.

mu is a forecast of the GROSS excess return (labels carry no slippage or charges), so slippage and charges are
subtracted here exactly once. The preliminary gate (spec 5.2 gates 4-5) is evaluated at the largest permissible
position; the chosen whole-share quantity is then re-checked with exact rupee-rounded charges at that quantity
(``position_gate``), together with exact cash at the order's cash price. A plan never contains a position that
fails its own gate at the size actually chosen.
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
    cash_price: float = 0.0  # funds blocked per share (e.g. the limit price); 0 = price

    def blocked_price(self) -> float:
        return self.cash_price if self.cash_price > 0 else self.price


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
        edge = 0.001 if saved.get("min_edge") is None else float(saved["min_edge"])
        tail = 0.08 if saved.get("tail_limit") is None else float(saved["tail_limit"])
        return Policy(W, reserve_fraction=reserve, cap_fraction=cap, K=K, gamma=2.0 / (m * W), min_edge=edge, tail_limit=tail)

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
    if not math.isnan(c.q10) and capital_tail_loss(c.q10, break_even(best) + c.slippage, best, policy) < -policy.tail_limit:
        reasons.append("TAIL_LIMIT")
    return (not reasons), reasons


def position_costs(c: Candidate, q: int) -> dict:
    """Exact round-trip costs of q shares at the decision price: buy and sell charges with rupee-rounded STT,
    the DP charge, and modelled slippage (rupees and fractions of the position value)."""
    v = q * c.price
    if q <= 0 or v <= 0:
        return {"value": 0.0, "charges": 0.0, "slippage": 0.0, "cost_fraction": float("inf")}
    dv = Decimal(str(round(v, 2)))
    buy = sum(charges(dv, side="BUY", style="delivery").values(), Decimal("0"))
    sell = sum(charges(dv, side="SELL", style="delivery", dp=True).values(), Decimal("0"))
    total = float(buy + sell)
    return {"value": round(v, 2), "buy_charges": float(buy), "sell_charges_incl_dp": float(sell), "charges": total,
            "slippage": round(v * c.slippage, 2), "charge_fraction": total / v, "cost_fraction": total / v + c.slippage}


def capital_tail_loss(q10: float, cost_fraction: float, position_value: float, policy: "Policy") -> float:
    """Gate 5 as a loss of capital (erratum E20): the bad-month (10%) outcome net of costs, times the position's share
    of capital. The spec compared q10 - cost to -L for the position alone, which rejects nearly every single stock
    (a typical month's 10% outcome is about -15%) and tightens perversely as positions shrink with diversification;
    the limit L is a statement about the account, so it is applied to the account."""
    w = position_value / policy.W if policy.W > 0 else 1.0
    return w * (q10 - cost_fraction)


def position_gate(c: Candidate, q: int, policy: "Policy") -> tuple[list[str], dict]:
    """Gates 4 and 5 at the actual whole-share quantity: mu - costs(q) >= m_min and q10 - costs(q) >= -L."""
    pc = position_costs(c, q)
    reasons = []
    net = c.mu - pc["cost_fraction"]
    if net < policy.min_edge:
        reasons.append("EDGE_BELOW_COST_AT_QUANTITY")
    if not math.isnan(c.q10) and capital_tail_loss(c.q10, pc["cost_fraction"], pc["value"], policy) < -policy.tail_limit:
        reasons.append("TAIL_LIMIT_AT_QUANTITY")
    return reasons, pc | {"net_edge": net, "threshold": pc["cost_fraction"] + policy.min_edge}


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
        spend += q * c.blocked_price() * (1 + BUY_VARIABLE)
        if c.sector:
            sectors[c.sector] = sectors.get(c.sector, 0.0) + v
    if held > policy.K or spend > cash_available + 1e-9:
        return False
    return all(v <= policy.sector_cap_fraction * policy.W + 1e-9 for v in sectors.values())


def exact_charges_feasible(qs: list[int], cands: list[Candidate], cash_available: float) -> bool:
    """Recompute buy-side charges with the cited fee schedule (rupee-rounded STT) at the blocked (cash) price
    before accepting a plan."""
    total = Decimal("0")
    for q, c in zip(qs, cands):
        if q > 0:
            v = Decimal(str(round(q * c.blocked_price(), 2)))
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
        total = sum(v * cands[i].blocked_price() / cands[i].price for v, i in zip(V, idx)) * (1 + BUY_VARIABLE)
        if total > cash_available:
            V = [v * cash_available / total for v in V]
        if not changed:
            break
    return V


def portfolio_tail_loss(qs, cands, policy) -> float:
    """The portfolio's bad-month loss as a share of capital when every held position has its bad month together
    (comonotone: the conservative case, since bad months cluster in a falling market). Each position contributes
    (value / W) * (q10 - cost at its quantity); the sum must stay within the one tail budget L (owner review
    2026-11-07: per-position limits alone let two -7% positions make -14%)."""
    total = 0.0
    for q, c in zip(qs, cands):
        if q > 0 and not math.isnan(c.q10):
            pc = position_costs(c, q)
            total += capital_tail_loss(c.q10, pc["cost_fraction"], pc["value"], policy)
    return total


def _accept(qs, subset, cands, policy, cash_available) -> bool:
    """Exact cash at the blocked price, every held position passes its gate at the chosen quantity, and the
    portfolio's combined bad-month loss stays within the tail limit."""
    if not exact_charges_feasible(qs, cands, cash_available):
        return False
    if not all(not position_gate(cands[i], qs[i], policy)[0] for i in subset if qs[i] > 0):
        return False
    return portfolio_tail_loss(qs, cands, policy) >= -policy.tail_limit


def max_quantity(c: Candidate, policy: Policy, cash_available: float | None = None) -> int:
    """The largest whole-share quantity the per-stock cap (and the cash, when given) allows at the decision price."""
    cap = policy.cap_fraction * policy.W
    room = cap if cash_available is None else min(cap, cash_available)
    return int(room // c.price) if c.price > 0 else 0


def qualifies(c: Candidate, policy: Policy, cash_available: float | None = None) -> bool:
    """Both gates pass at the largest affordable quantity (what the stock's card shows). The allocation pool is
    built from these, so a stock that passes only the coarse at-cap gate cannot crowd out one that really
    qualifies (owner review 2026-11-07: CGPOWER and RRKABEL were labelled NOT_IN_TOP_10_POOL)."""
    q = max_quantity(c, policy, cash_available)
    return q > 0 and entry_gate(c, policy)[0] and not position_gate(c, q, policy)[0]


def standalone_utility(c: Candidate, policy: Policy, cash_available: float | None = None) -> dict:
    """The allocator's objective for this stock alone at every whole-share quantity, and its best: expected net
    rupees after variable costs and slippage, the fixed DP fee, and the risk penalty gamma/2 (V sigma)^2. Holding
    cash scores 0, so a best utility at or below 0 means the allocator rationally prefers cash."""
    g = policy.risk_aversion()
    best = None
    for q in range(1, max_quantity(c, policy, cash_available) + 1):
        v = q * c.price
        gain = (c.mu - VARIABLE_ROUND_TRIP - c.slippage) * v
        risk = g / 2 * (v * c.sigma) ** 2
        u = gain - FIXED_SELL - risk
        if best is None or u > best["utility"]:
            best = {"q": q, "value": round(v, 2), "expected_net_rupees": round(gain, 2), "dp_fee": FIXED_SELL,
                    "risk_penalty": round(risk, 2), "utility": round(u, 2)}
    out = best or {"q": 0, "utility": None}
    out.update(cash_utility=0.0, gamma=g, mu=c.mu, sigma=c.sigma,
               prefers_cash=best is None or best["utility"] <= 0)
    return out


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
                        if val > best[0] and _accept(qs, subset, cands, policy, cash_available):
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
                        if val > best[0] and _accept(qs, subset, cands, policy, cash_available):
                            best = (val, qs[:], "neighbourhood")
                    for i in subset:
                        qs[i] = 0
    val, qs, method = best
    positions = {cands[i].isin: position_gate(cands[i], q, policy)[1] | {"q": q}
                 for i, q in enumerate(qs) if q > 0}
    at_quantity = {}
    for c in passing:
        if c.isin not in positions:
            best_q = int(min(cap, policy.W * (1 - policy.reserve_fraction)) // c.price) if c.price > 0 else 0
            reasons = position_gate(c, best_q, policy)[0] if best_q > 0 else ["NO_WHOLE_SHARE_FITS"]
            if reasons:
                at_quantity[c.isin] = reasons
    if method == "cash" and at_quantity:
        rejected.update(at_quantity)
    return {"quantities": {cands[i].isin: q for i, q in enumerate(qs) if q > 0}, "objective": val,
            "values": {cands[i].isin: round(q * cands[i].price, 2) for i, q in enumerate(qs) if q > 0},
            "positions": positions, "rejected": rejected, "method": method}


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
