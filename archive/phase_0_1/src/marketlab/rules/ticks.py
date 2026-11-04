"""Price-linked tick sizes for NSE CM equity series (EQ, T0, BE, BZ, BO, RL, AF and BL).

Tick size is reviewed monthly: the close on the last trading day of the previous month sets
the tick for the next month. Prefer the exchange security file's tick when it is loaded; this
schedule is the fallback and the cross-check. ETFs are excluded from this schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .provenance import Cite, Status
from .types import RuleUnknown

TICK_SERIES = frozenset({"EQ", "T0", "BE", "BZ", "BO", "RL", "AF", "BL"})


@dataclass(frozen=True, slots=True)
class TickRegime:
    effective_from: date
    effective_to: date | None  # inclusive
    # (upper bound inclusive or None for open-ended, tick); first matching slab wins.
    # The "below 250" slab is exclusive at 250, encoded with an exclusive flag.
    slabs: tuple[tuple[Decimal | None, bool, Decimal], ...]
    cite: Cite


D = Decimal

TICK_REGIMES: tuple[TickRegime, ...] = (
    TickRegime(
        effective_from=date(2024, 6, 10),
        effective_to=date(2025, 4, 14),
        slabs=((D("250"), True, D("0.01")), (None, False, D("0.05"))),
        cite=Cite(("NSE/CMTR/67133", "NSE/TICK-2024-SUMMARY"), Status.SECONDARY,
                  "Slab values from the 'current tick' column of NSE/CMTR/67133 (primary); the 10 Jun 2024 "
                  "start date is from a search summary of NSE/CMTR/62174."),
    ),
    TickRegime(
        effective_from=date(2025, 4, 15),
        effective_to=None,
        slabs=(
            (D("250"), True, D("0.01")),      # below 250
            (D("1000"), False, D("0.05")),    # 250 to 1,000
            (D("5000"), False, D("0.10")),    # >1,000 to 5,000
            (D("10000"), False, D("0.50")),   # >5,000 to 10,000
            (D("20000"), False, D("1.00")),   # >10,000 to 20,000
            (None, False, D("5.00")),         # >20,000
        ),
        cite=Cite(("NSE/CMTR/67133", "NSE/CMTR/73927"), Status.PRIMARY,
                  "Price-linked tick table effective 15 Apr 2025, reviewed monthly (consolidated section 3.3)."),
    ),
)


def regime_for(on: date) -> TickRegime:
    for r in TICK_REGIMES:
        if r.effective_from <= on and (r.effective_to is None or on <= r.effective_to):
            return r
    raise RuleUnknown(f"No verified tick-size regime loaded for {on}")


def tick_size(reference_price: Decimal, on: date) -> Decimal:
    if reference_price <= 0:
        raise ValueError("Reference price must be positive")
    for bound, exclusive, tick in regime_for(on).slabs:
        if bound is None:
            return tick
        if (reference_price < bound) if exclusive else (reference_price <= bound):
            return tick
    raise AssertionError("unreachable: last slab is open-ended")


def is_on_tick(price: Decimal, tick: Decimal) -> bool:
    return price % tick == 0


def floor_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def ceil_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_CEILING) * tick
