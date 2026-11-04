"""Price bands, exchange market-price protection, SL-limit validation and market-wide circuit breakers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from .provenance import Cite, Status
from .ticks import ceil_to_tick, floor_to_tick

D = Decimal
HUNDRED = D("100")

BAND_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                 "Static bands for non-F&O stocks set by surveillance; F&O stocks have no band but a 10% "
                 "dynamic operating range that can flex (section 3.1).")
BAND_ROUNDING_CITE = Cite(("NSE/CMTR/73927",), Status.ASSUMPTION,
                          "Band prices are 'aligned as per tick size'; the direction is not stated. We round the "
                          "upper limit down and the lower limit up so every accepted price is inside the band.")
CAS_BAND_CITE = Cite(("NSE/CMTR/73362", "SEBI/CAS-2026"), Status.PRIMARY,
                     "CAS price band is +/-3% of the CAS reference price (VWAP 15:00-15:15).")
MPP_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                "Market orders trade only up to LTP +/-3% (LTP > Rs 50) or +/-Rs 1.5 (LTP <= Rs 50); market "
                "orders are rejected if the security has not traded today (section 3.6 A).")
SL_GAP_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                   "SL-limit rejected if |limit - trigger| exceeds 3% of trigger (trigger > Rs 50) or Rs 1.5 "
                   "(trigger <= Rs 50) (section 3.6 B).")
MWCB_CITE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                 "Index circuit filter at 10/15/20% of previous Nifty 50 close (section 3.7).")


@dataclass(frozen=True, slots=True)
class Band:
    lower: Decimal
    upper: Decimal


def static_band(base_price: Decimal, band_pct: Decimal, tick: Decimal, no_upward_movement: bool = False) -> Band:
    if base_price <= 0 or band_pct <= 0 or tick <= 0:
        raise ValueError("base_price, band_pct and tick must be positive")
    upper = floor_to_tick(base_price * (1 + band_pct / HUNDRED), tick)
    lower = ceil_to_tick(base_price * (1 - band_pct / HUNDRED), tick)
    if no_upward_movement:
        upper = floor_to_tick(base_price, tick)
    return Band(lower=lower, upper=upper)


def cas_band(reference_price: Decimal, tick: Decimal) -> Band:
    return static_band(reference_price, D("3"), tick)


def mpp_offset(ltp: Decimal) -> Decimal:
    """Exchange market-price-protection distance from LTP."""
    return D("1.5") if ltp <= 50 else ltp * D("0.03")


def mpp_limits(ltp: Decimal) -> Band:
    off = mpp_offset(ltp)
    return Band(lower=ltp - off, upper=ltp + off)


def sl_limit_gap_allowed(trigger: Decimal) -> Decimal:
    return D("1.5") if trigger <= 50 else trigger * D("0.03")


@dataclass(frozen=True, slots=True)
class CircuitHalt:
    halt_minutes: int | None  # None => market closed for the rest of the day
    resumes_with_preopen: bool


def market_wide_circuit(level_pct: int, triggered_at: time) -> CircuitHalt:
    """Index-based market-wide circuit breaker outcome (halt includes the 15-min pre-open on resumption)."""
    one_pm, two_pm, two_thirty = time(13, 0), time(14, 0), time(14, 30)
    if level_pct == 10:
        if triggered_at < one_pm:
            return CircuitHalt(45, True)
        if triggered_at < two_thirty:
            return CircuitHalt(15, True)
        return CircuitHalt(0, False)
    if level_pct == 15:
        if triggered_at < one_pm:
            return CircuitHalt(105, True)
        if triggered_at < two_pm:
            return CircuitHalt(45, True)
        return CircuitHalt(None, False)
    if level_pct == 20:
        return CircuitHalt(None, False)
    raise ValueError("Circuit levels are 10, 15 or 20 percent")
