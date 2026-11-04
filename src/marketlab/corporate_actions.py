"""Corporate actions and price-series provenance (review of 3513d33, finding 4).

Three kinds of price data are never mixed:

* PROVIDER_ORIGINAL: the bytes a provider returned, with their retrieval vintage. Kite historical
  candles are adjusted by Zerodha for bonus, split, rights, spin-off and extraordinary (>= 2%) dividends
  before market open on each ex-date (KITE/CA-ADJUSTMENT, KITE/CA-FORUM-15971). A later download of the
  same dates can therefore differ; each vintage is kept.
* EXCHANGE_UNADJUSTED: prices actually traded on the exchange (bhavcopy). These decide historical
  affordability, bands, ticks and integer share counts.
* DERIVED_ADJUSTED / DERIVED_TOTAL_RETURN: analytical series derived from EXCHANGE_UNADJUSTED by
  applying listed actions. They record the action IDs they applied, so no action is applied twice, and
  a provider series whose adjustment basis is unknown cannot be adjusted again.

Positions change on the ex-date (quantity for splits and bonuses) while dividend cash arrives on the
payment date; between the two it is a receivable, not cash. Fractional entitlements and taxes are not
modelled and are reported instead of being guessed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

D = Decimal


class SeriesKind(StrEnum):
    PROVIDER_ORIGINAL = "PROVIDER_ORIGINAL"
    EXCHANGE_UNADJUSTED = "EXCHANGE_UNADJUSTED"
    DERIVED_ADJUSTED = "DERIVED_ADJUSTED"
    DERIVED_TOTAL_RETURN = "DERIVED_TOTAL_RETURN"


class AdjustmentBasis(StrEnum):
    NONE = "NONE"  # actual traded prices
    PROVIDER_AS_OF_RETRIEVAL = "PROVIDER_AS_OF_RETRIEVAL"  # adjusted by the provider; basis not enumerated
    LISTED_ACTIONS = "LISTED_ACTIONS"  # adjusted here; see applied_action_ids


class ActionKind(StrEnum):
    SPLIT = "SPLIT"  # face value old_fv -> new_fv
    BONUS = "BONUS"  # `ratio_new` new shares for every `ratio_held` held
    DIVIDEND = "DIVIDEND"  # cash per share
    RIGHTS = "RIGHTS"  # not modelled: needs subscription decision and price
    SPIN_OFF = "SPIN_OFF"  # not modelled: needs cost-of-acquisition split and a new security


class DoubleAdjustment(ValueError):
    """Adjusting would apply an action twice or adjust data whose adjustment basis is unknown."""


class Unmodelled(ValueError):
    """The action needs information this module does not model (rights, spin-offs, fractions)."""


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    isin: str
    kind: ActionKind
    ex_date: date
    record_date: date | None
    payment_date: date | None = None  # dividends: cash arrives here, not on the ex-date
    old_fv: Decimal | None = None
    new_fv: Decimal | None = None
    ratio_new: int | None = None
    ratio_held: int | None = None
    cash_per_share: Decimal | None = None
    source: str = ""
    published_at: datetime | None = None  # when first announced/published
    first_seen_at: datetime | None = None  # when this system first received it

    def __post_init__(self):
        if self.kind is ActionKind.SPLIT and not (self.old_fv and self.new_fv and self.old_fv > 0 and self.new_fv > 0):
            raise ValueError("A split needs positive old and new face values")
        if self.kind is ActionKind.BONUS and not (self.ratio_new and self.ratio_held and self.ratio_new > 0
                                                  and self.ratio_held > 0):
            raise ValueError("A bonus needs a positive ratio")
        if self.kind is ActionKind.DIVIDEND and not (self.cash_per_share and self.cash_per_share > 0):
            raise ValueError("A dividend needs a positive cash amount per share")

    def price_factor(self, previous_close: Decimal | None = None) -> Decimal:
        """Multiply prices dated before the ex-date by this factor to make them comparable after it."""
        if self.kind is ActionKind.SPLIT:
            return self.new_fv / self.old_fv
        if self.kind is ActionKind.BONUS:
            return D(self.ratio_held) / D(self.ratio_held + self.ratio_new)
        if self.kind is ActionKind.DIVIDEND:
            if previous_close is None or previous_close <= self.cash_per_share:
                raise Unmodelled("A total-return dividend factor needs the close before the ex-date")
            return (previous_close - self.cash_per_share) / previous_close
        raise Unmodelled(f"{self.kind} adjustments are not modelled")


@dataclass(frozen=True, slots=True)
class Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class PriceSeries:
    series_id: str
    kind: SeriesKind
    isin: str
    exchange: str
    source: str
    retrieved_at: datetime  # vintage: when these exact values were obtained (or derived)
    basis: AdjustmentBasis
    bars: tuple[Bar, ...]
    applied_action_ids: tuple[str, ...] = ()
    parent_series_id: str | None = None
    notes: tuple[str, ...] = field(default=())

    def digest(self) -> str:
        rows = [[b.day.isoformat(), str(b.open), str(b.high), str(b.low), str(b.close), b.volume] for b in self.bars]
        return hashlib.sha256(json.dumps([self.kind, self.isin, self.exchange, self.basis, rows]).encode()).hexdigest()


def provider_series(isin, exchange, source, retrieved_at, bars, series_id) -> PriceSeries:
    """Kite (or any provider) candles as received. Adjustment basis is the provider's, as of retrieval."""
    return PriceSeries(series_id, SeriesKind.PROVIDER_ORIGINAL, isin, exchange, source, retrieved_at,
                       AdjustmentBasis.PROVIDER_AS_OF_RETRIEVAL, tuple(bars),
                       notes=("Provider-adjusted for bonus/split/rights/spin-off/extraordinary dividends as of "
                              "retrieval; not actual traded prices",))


def adjust(series: PriceSeries, actions, *, total_return=False, derived_at: datetime, series_id: str) -> PriceSeries:
    """Derive an adjusted (or total-return) series from actual exchange prices.

    Refuses provider data with an unknown basis, actions for another security, actions already
    applied, and actions this module cannot model. Volumes are scaled inversely for splits/bonuses.
    """
    if series.kind is not SeriesKind.EXCHANGE_UNADJUSTED or series.basis is not AdjustmentBasis.NONE:
        raise DoubleAdjustment("Only actual exchange prices may be adjusted; provider data may already be adjusted")
    actions = sorted(actions, key=lambda a: (a.ex_date, a.action_id))
    ids = [a.action_id for a in actions]
    if len(set(ids)) != len(ids) or set(ids) & set(series.applied_action_ids):
        raise DoubleAdjustment("An action would be applied twice")
    bars = list(series.bars)
    closes = {b.day: b.close for b in bars}
    for a in actions:
        if a.isin != series.isin:
            raise ValueError(f"Action {a.action_id} is for another security")
        if a.kind is ActionKind.DIVIDEND and not total_return:
            continue  # ordinary price-adjusted series ignore dividends; total return includes them
        before = [b.day for b in bars if b.day < a.ex_date]
        prev_close = closes.get(max(before)) if before else None
        f = a.price_factor(prev_close)
        volume_scale = (1 / f) if a.kind in (ActionKind.SPLIT, ActionKind.BONUS) else D(1)
        bars = [replace(b, open=b.open * f, high=b.high * f, low=b.low * f, close=b.close * f,
                        volume=int((D(b.volume) * volume_scale).to_integral_value()))
                if b.day < a.ex_date else b for b in bars]
    applied = tuple(a.action_id for a in actions if total_return or a.kind is not ActionKind.DIVIDEND)
    return PriceSeries(series_id, SeriesKind.DERIVED_TOTAL_RETURN if total_return else SeriesKind.DERIVED_ADJUSTED,
                       series.isin, series.exchange, "derived:" + series.series_id, derived_at,
                       AdjustmentBasis.LISTED_ACTIONS, tuple(bars), series.applied_action_ids + applied,
                       series.series_id)


@dataclass(frozen=True, slots=True)
class PositionEffect:
    quantity: int
    cost_total: Decimal  # unchanged by splits/bonuses; cost per share falls
    dividend_receivable: Decimal  # owed, not yet cash
    dividend_payment_date: date | None
    notes: tuple[str, ...] = ()


def apply_to_position(quantity_entitled: int, cost_total: Decimal, action: CorporateAction) -> PositionEffect:
    """Effect on a holding of shares entitled on the record date (under T+1, held at the end of the day
    before the ex-date). Fractional bonus/split entitlements are refused rather than rounded."""
    q, cost = quantity_entitled, cost_total
    if q < 0:
        raise ValueError("Cash-only scope: no short positions")
    if action.kind is ActionKind.SPLIT:
        new_q = D(q) * action.old_fv / action.new_fv
        if new_q != new_q.to_integral_value():
            raise Unmodelled("Split leaves a fractional entitlement (cash in lieu is not modelled)")
        return PositionEffect(int(new_q), cost, D(0), None)
    if action.kind is ActionKind.BONUS:
        extra = D(q) * action.ratio_new / action.ratio_held
        if extra != extra.to_integral_value():
            whole = int(extra.to_integral_value(rounding=ROUND_FLOOR))
            return PositionEffect(q + whole, cost, D(0), None,
                                  ("FRACTIONAL_BONUS_ENTITLEMENT_UNMODELLED",))
        return PositionEffect(q + int(extra), cost, D(0), None)
    if action.kind is ActionKind.DIVIDEND:
        if action.payment_date is None:
            raise Unmodelled("Dividend payment date unknown; cash cannot be scheduled")
        return PositionEffect(q, cost, action.cash_per_share * q, action.payment_date, ("TDS_UNMODELLED",))
    raise Unmodelled(f"{action.kind} is not modelled")


def reconcile_provider(provider: PriceSeries, exchange: PriceSeries, actions, *, tolerance=D("0.005")) -> dict:
    """Is the provider series the exchange series adjusted by exactly these actions (as of its vintage)?

    For each common day, the expected ratio provider/exchange is the product of the split/bonus factors
    of actions with ex-date after that day and on or before the provider's retrieval date. Returns
    per-day rows and the days that disagree; it never edits either series.
    """
    if provider.kind is not SeriesKind.PROVIDER_ORIGINAL or exchange.kind is not SeriesKind.EXCHANGE_UNADJUSTED:
        raise ValueError("Compare a provider original with actual exchange prices")
    vintage = provider.retrieved_at.date()
    relevant = [a for a in actions if a.kind in (ActionKind.SPLIT, ActionKind.BONUS) and a.ex_date <= vintage]
    ex = {b.day: b for b in exchange.bars}
    rows, mismatches = [], []
    for b in provider.bars:
        if b.day not in ex or ex[b.day].close == 0:
            continue
        expected = D(1)
        for a in relevant:
            if b.day < a.ex_date:
                expected *= a.price_factor()
        observed = b.close / ex[b.day].close
        ok = abs(observed - expected) <= tolerance * expected
        rows.append({"day": b.day, "observed_ratio": observed, "expected_ratio": expected, "ok": ok})
        if not ok:
            mismatches.append(b.day)
    return {"days": len(rows), "mismatched_days": mismatches, "consistent": bool(rows) and not mismatches,
            "rows": rows}
