"""Core value types for the rules engine. Money and prices are Decimal; times are tz-aware."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

# India has observed a fixed +05:30 offset with no DST since 1945, so a fixed offset is exact
# and avoids depending on an IANA tz database (Windows Python ships none).
IST = timezone(timedelta(hours=5, minutes=30), "IST")


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Product(StrEnum):
    CNC = "CNC"  # cash and carry (delivery)
    MIS = "MIS"  # intraday, auto square-off
    MTF = "MTF"  # margin trading facility (broker-funded delivery)


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    SL = "SL"  # stop-loss limit
    SL_M = "SL-M"  # stop-loss market


class Validity(StrEnum):
    DAY = "DAY"
    IOC = "IOC"
    TTL = "TTL"


class Framework(StrEnum):
    """Exchange surveillance frameworks a security can be placed under."""

    GSM = "GSM"  # Graded Surveillance Measure
    LT_ASM = "LT_ASM"  # Long-term Additional Surveillance Measure
    ST_ASM = "ST_ASM"  # Short-term Additional Surveillance Measure
    ESM = "ESM"  # Enhanced Surveillance Measure (micro/small caps)
    IBC = "IBC"  # companies under Insolvency and Bankruptcy Code
    USM = "USM"  # unsolicited SMS/media category
    LOW_NPH = "LOW_NPH"  # non-promoter holding below 25%


@dataclass(frozen=True, slots=True)
class SurveillanceFlag:
    framework: Framework
    stage: int  # framework-specific; 0 used where a framework has a "Stage 0"


@dataclass(frozen=True, slots=True)
class InstrumentSnapshot:
    """Point-in-time state of one exchange listing, as known before the decision.

    ``None`` means *unknown*. Required unknowns block an order; they are never defaulted.
    """

    as_of: date  # trading date this snapshot describes
    exchange: Exchange
    symbol: str
    isin: str
    series: str  # NSE series (EQ, BE, BZ, ...) or BSE group (A, B, T, XT, Z, ...)
    has_derivatives: bool | None  # F&O stocks: no static band, CAS applies from 2026-08-03
    base_price: Decimal | None  # previous close / adjusted base price for today
    price_band_pct: Decimal | None  # static band (2, 5, 10, 20) for non-F&O; None when unknown
    tick_size: Decimal | None = None  # from the exchange security file, if loaded
    tick_reference_price: Decimal | None = None  # last-trading-day-of-previous-month close
    ltp: Decimal | None = None  # last traded price today; None = not traded today / unknown
    dynamic_band_pct: Decimal | None = None  # F&O operating range currently in force (10 unless flexed)
    cas_reference_price: Decimal | None = None  # VWAP 15:00-15:15 (needed during CAS)
    surveillance: frozenset[SurveillanceFlag] | None = frozenset()  # None = list not loaded
    in_periodic_call_auction: bool | None = False
    suspended: bool | None = False
    special_preopen_today: bool | None = False  # IPO/relisting day call auction
    mis_eligible: bool | None = None  # broker's intraday list
    mtf_eligible: bool | None = None  # broker's approved MTF list
    var_pct: Decimal | None = None  # VaR margin % (for MTF margin)
    elm_pct: Decimal | None = None  # extreme loss margin %
    in_nifty500: bool | None = None  # for broker MTF per-stock exposure caps
    snapshot_id: str = ""


@dataclass(frozen=True, slots=True)
class OrderRequest:
    submitted_at: datetime  # must be timezone-aware
    exchange: Exchange
    side: Side
    product: Product
    order_type: OrderType
    quantity: int
    price: Decimal | None = None  # limit price (LIMIT, SL)
    trigger_price: Decimal | None = None  # SL, SL-M
    validity: Validity = Validity.DAY
    market_protection_pct: Decimal | None = None  # Kite API: required for MARKET and SL-M
    via_api: bool = True
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class PositionState:
    """What the account holds in this instrument at decision time (quantities in shares)."""

    settled_qty: int = 0  # free in demat (CNC)
    t1_qty: int = 0  # bought on earlier trading day(s), not yet credited (BTST candidates)
    bought_today_qty: int = 0  # CNC bought today
    mtf_qty: int = 0  # MTF holdings (pledged)
    mis_net_qty: int = 0  # today's intraday net (+long / -short)
    pending_sell_qty: int = 0  # open sell orders already resting


@dataclass(frozen=True, slots=True)
class AccountState:
    ddpi_enabled: bool | None = None  # required by Zerodha for MTF
    resident_individual: bool | None = None  # NRIs/minors not eligible for Zerodha MTF
    mtf_total_exposure_inr: Decimal = Decimal("0")
    mtf_stock_exposure_inr: Decimal = Decimal("0")  # existing MTF exposure in this stock


@dataclass(frozen=True, slots=True)
class Policy:
    """Our own scope decisions. These are not exchange rules and are reported as POLICY reasons."""

    allowed_exchanges: frozenset[Exchange] = frozenset({Exchange.NSE, Exchange.BSE})
    allowed_products: frozenset[Product] = frozenset({Product.CNC, Product.MTF})
    allow_short_selling: bool = False
    limit_only_in_auctions: bool = True  # no market orders in pre-open/CAS (no LTP basis for protection)
    require_explicit_market_protection: bool = True  # Kite's -1 'auto' protection band is unverified
    max_market_protection_pct: Decimal = Decimal("5")
    allow_unverified_t2t_next_day_sale: bool = False


class Outcome(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    outcome: Outcome
    message: str
    sources: tuple[str, ...] = ()
    status: str = ""
    values: tuple[tuple[str, str], ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Decision:
    accepted: bool
    checks: tuple[Check, ...]
    effective_limit_price: Decimal | None = None  # limit price, or the protected limit of an API market order
    session: str = ""

    @property
    def blocks(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.outcome is Outcome.BLOCK)

    @property
    def warnings(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.outcome is Outcome.WARN)

    def codes(self, outcome: Outcome | None = None) -> set[str]:
        return {c.code for c in self.checks if outcome is None or c.outcome is outcome}

    def explain(self) -> str:
        """Deterministic plain-text explanation built only from recorded checks."""
        head = "ACCEPTED" if self.accepted else "REJECTED"
        lines = [f"{head} (session: {self.session or 'n/a'})"]
        for c in self.checks:
            if c.outcome is not Outcome.PASS:
                lines.append(f"  [{c.outcome}] {c.code}: {c.message}")
        if self.effective_limit_price is not None:
            lines.append(f"  Effective limit price: {self.effective_limit_price}")
        return "\n".join(lines)


class RuleUnknown(Exception):
    """Raised when a rule cannot be evaluated because required rule data is not loaded."""
