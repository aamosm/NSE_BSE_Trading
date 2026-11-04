"""Margin Trading Facility (MTF) entry rules at Zerodha (observed 2026-11-04).

Ledger mechanics (lots, funded principal, interest accrual calendar, pledge lifecycle) belong to
Phase 1. This module only answers: may an MTF buy be proposed, and how much must the client fund?
"""

from __future__ import annotations

from decimal import Decimal

from .provenance import Cite, Status

D = Decimal

MTF_CITE = Cite(("ZERODHA/MTF-FAQ",), Status.BROKER_OFFICIAL,
                "Approved-list stocks only; DDPI/POA required; NRIs, minors and custodial participants excluded; "
                "margin VaR + 3x ELM (F&O stocks) or VaR + 5x ELM (others); interest 0.04%/day on the funded "
                "amount from T+1 until sold; auto-pledge on buy; no maximum holding period; BTST allowed.")
MTF_INTEREST_DAYCOUNT_CITE = Cite(("ZERODHA/MTF-FAQ",), Status.UNKNOWN,
                                  "Whether weekends/holidays accrue, and sale-day treatment, must be verified "
                                  "against MTF ledger entries before Phase 1 fixtures are final.")

MTF_DAILY_INTEREST_PCT = D("0.04")

# Per-account and per-stock MTF exposure ceilings (rupees).
MTF_ACCOUNT_CAP = D("500000000")  # Rs 50 crore
MTF_STOCK_CAP_NIFTY500 = D("120000000")  # Rs 12 crore
MTF_STOCK_CAP_LARGE_FREE_FLOAT = D("70000000")  # Rs 7 crore (> Rs 1,000 cr free-float m-cap)
MTF_STOCK_CAP_OTHER = D("30000000")  # Rs 3 crore


def mtf_margin_pct(var_pct: Decimal, elm_pct: Decimal, has_derivatives: bool) -> Decimal:
    """Client-funded share of the purchase value, in percent, capped at 100."""
    if var_pct < 0 or elm_pct < 0:
        raise ValueError("VaR and ELM must be non-negative")
    multiple = 3 if has_derivatives else 5
    return min(var_pct + multiple * elm_pct, D("100"))


def mtf_split(value: Decimal, margin_pct: Decimal) -> tuple[Decimal, Decimal]:
    """(client contribution, broker-funded amount) for a purchase value. Unrounded."""
    client = value * margin_pct / 100
    return client, value - client


def mtf_stock_cap(in_nifty500: bool | None, large_free_float: bool | None = None) -> Decimal:
    """Per-stock ceiling; unknown membership falls to the strictest cap."""
    if in_nifty500:
        return MTF_STOCK_CAP_NIFTY500
    if large_free_float:
        return MTF_STOCK_CAP_LARGE_FREE_FLOAT
    return MTF_STOCK_CAP_OTHER


def mtf_interest_for_days(funded: Decimal, chargeable_days: int) -> Decimal:
    """Simple interest at 0.04%/day. Which days are chargeable is a Phase 1 rule (see UNKNOWN cite)."""
    if chargeable_days < 0:
        raise ValueError("chargeable_days must be non-negative")
    return funded * MTF_DAILY_INTEREST_PCT / 100 * chargeable_days
