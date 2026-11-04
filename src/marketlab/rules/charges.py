"""Zerodha equity charge schedule (snapshot observed 2026-11-04) and per-order charge computation.

Rounding is an explicit ASSUMPTION until reconciled with real contract notes: each component is
computed at full precision and rounded to the paisa (half-up); GST is computed on the unrounded
GST base and then rounded. Contract notes may round STT/stamp differently.

Applying this schedule to dates before ``observed_on`` is a *current-rule counterfactual* and is
flagged as such by ``order_charges``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .provenance import Cite, Status
from .types import Exchange, Side

D = Decimal
PAISA = D("0.01")
CRORE = D("10000000")


class TradeKind(StrEnum):
    DELIVERY = "DELIVERY"  # CNC, including BTST
    INTRADAY = "INTRADAY"  # MIS, or a CNC buy and sell of the same shares on the same day


@dataclass(frozen=True, slots=True)
class Brokerage:
    pct: Decimal  # percent of order turnover
    cap: Decimal | None  # rupees per executed order


@dataclass(frozen=True, slots=True)
class ChargeSchedule:
    observed_on: date
    brokerage: dict[TradeKind, Brokerage]
    stt_pct: dict[tuple[TradeKind, Side], Decimal]
    stamp_buy_pct: dict[TradeKind, Decimal]
    nse_txn_pct: Decimal
    bse_txn_pct_by_group: dict[str, Decimal]
    bse_txn_pct_default: Decimal
    sebi_per_crore: Decimal
    nse_ipft_per_crore: Decimal
    gst_pct: Decimal
    dp_charge_per_scrip_incl_gst: Decimal
    auto_square_off_fee: Decimal  # + GST, per order squared off by the broker's dealer
    cites: tuple[Cite, ...] = field(default=())


ZERODHA_2026_11_04 = ChargeSchedule(
    observed_on=date(2026, 11, 4),
    brokerage={
        TradeKind.DELIVERY: Brokerage(D("0"), None),
        TradeKind.INTRADAY: Brokerage(D("0.03"), D("20")),
    },
    stt_pct={
        (TradeKind.DELIVERY, Side.BUY): D("0.1"), (TradeKind.DELIVERY, Side.SELL): D("0.1"),
        (TradeKind.INTRADAY, Side.BUY): D("0"), (TradeKind.INTRADAY, Side.SELL): D("0.025"),
    },
    stamp_buy_pct={TradeKind.DELIVERY: D("0.015"), TradeKind.INTRADAY: D("0.003")},
    nse_txn_pct=D("0.00307"),
    bse_txn_pct_by_group={
        # Rs 10,000 per crore = 0.1%
        "X": D("0.1"), "XT": D("0.1"), "Z": D("0.1"), "ZP": D("0.1"),
        # Rs 1,00,000 per crore = 1%
        "SS": D("1"), "ST": D("1"),
        # Rs 275 per crore = 0.00275%
        "M": D("0.00275"), "MT": D("0.00275"), "TS": D("0.00275"), "MS": D("0.00275"),
    },
    bse_txn_pct_default=D("0.00375"),
    sebi_per_crore=D("10"),
    nse_ipft_per_crore=D("0.01"),
    gst_pct=D("18"),
    dp_charge_per_scrip_incl_gst=D("15.34"),
    auto_square_off_fee=D("50"),
    cites=(
        Cite(("ZERODHA/CHARGES",), Status.BROKER_OFFICIAL, "All rates as listed on 2026-11-04."),
        Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
             "Per-component paisa rounding (half-up); GST on the unrounded base. Reconcile with contract notes."),
        Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
             "DP charge applied once per ISIN per sell date ('per scrip, irrespective of quantity')."),
    ),
)


def _r(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ChargeBreakdown:
    turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    sebi: Decimal
    ipft: Decimal
    stamp: Decimal
    gst: Decimal
    counterfactual: bool  # schedule applied to a date before it was observed

    @property
    def total(self) -> Decimal:
        return self.brokerage + self.stt + self.exchange_txn + self.sebi + self.ipft + self.stamp + self.gst


def order_charges(schedule: ChargeSchedule, *, exchange: Exchange, kind: TradeKind, side: Side,
                  price: Decimal, quantity: int, trade_date: date, bse_group: str | None = None) -> ChargeBreakdown:
    """Charges for one executed order (all its fills), excluding DP/pledge charges which are per day/ISIN."""
    if quantity <= 0 or price <= 0:
        raise ValueError("price and quantity must be positive")
    turnover = price * quantity
    b = schedule.brokerage[kind]
    brokerage_raw = turnover * b.pct / 100
    if b.cap is not None:
        brokerage_raw = min(brokerage_raw, b.cap)
    stt_raw = turnover * schedule.stt_pct[(kind, side)] / 100
    if exchange is Exchange.NSE:
        txn_pct = schedule.nse_txn_pct
        ipft_raw = turnover * schedule.nse_ipft_per_crore / CRORE
    else:
        if bse_group is None:
            raise ValueError("BSE charges depend on the scrip group; pass bse_group")
        txn_pct = schedule.bse_txn_pct_by_group.get(bse_group.upper(), schedule.bse_txn_pct_default)
        ipft_raw = D("0")
    txn_raw = turnover * txn_pct / 100
    sebi_raw = turnover * schedule.sebi_per_crore / CRORE
    stamp_raw = turnover * schedule.stamp_buy_pct[kind] / 100 if side is Side.BUY else D("0")
    gst_raw = (brokerage_raw + txn_raw + sebi_raw + ipft_raw) * schedule.gst_pct / 100
    return ChargeBreakdown(
        turnover=turnover,
        brokerage=_r(brokerage_raw),
        stt=_r(stt_raw),
        exchange_txn=_r(txn_raw),
        sebi=_r(sebi_raw),
        ipft=_r(ipft_raw),
        stamp=_r(stamp_raw),
        gst=_r(gst_raw),
        counterfactual=trade_date < schedule.observed_on,
    )


def with_gst(schedule: ChargeSchedule, fee: Decimal) -> Decimal:
    return _r(fee * (1 + schedule.gst_pct / 100))


def dp_charges(schedule: ChargeSchedule, sell_days: set[tuple[str, date]]) -> Decimal:
    """DP charge for delivery sells: one charge per (ISIN, sell date). Not charged on MIS."""
    return schedule.dp_charge_per_scrip_incl_gst * len(sell_days)


# ---- Day-level statutory aggregation (review of 3513d33, finding 5) -------------------------------

RUPEE = D("1")
STT_BASIS_CITE = Cite(("ZERODHA/STT-ROUNDING", "STT-RULES-2004-DRAFT", "NSE/INSP/45900"), Status.ASSUMPTION,
                      "STT per exchange, client, ISIN, trade date, trade kind and side: aggregate value / quantity "
                      "rounded to the paisa, STT on that, rounded to the nearest rupee (50 paise and above up). "
                      "Basis from the 2004 draft STT rules; Zerodha documents the rupee rounding; contract-note STT "
                      "is an integer field. Unreconciled with a real contract note.")
STAMP_CITE = Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
                  "Stamp duty allocation and rounding UNRESOLVED: per-order paisa rounding is assumed.")
DP_CITE = Cite(("ZERODHA/DP-CHARGES",), Status.BROKER_OFFICIAL,
               "DP charge once per scrip per sell day irrespective of quantity; posted to the funds statement, "
               "not the contract note. Rs 15.34 incl. GST for a male primary holder, Rs 15.05 for a female "
               "primary holder (account-specific; reconcile with the funds statement).")
DAY_ASSUMPTIONS = ("STT_AGGREGATION_UNRECONCILED", "STAMP_ALLOCATION_UNRESOLVED", "DP_FROM_FUNDS_STATEMENT")


def round_rupee(x: Decimal) -> Decimal:
    return x.quantize(RUPEE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Fill:
    trade_date: date
    exchange: Exchange
    isin: str
    kind: TradeKind
    side: Side
    price: Decimal
    quantity: int
    order_id: str
    bse_group: str | None = None


@dataclass(frozen=True, slots=True)
class SttGroup:
    trade_date: date
    exchange: Exchange
    isin: str
    kind: TradeKind
    side: Side
    quantity: int
    turnover: Decimal
    average_price: Decimal  # turnover / quantity, rounded to the paisa
    stt: Decimal  # whole rupees


@dataclass(frozen=True, slots=True)
class DayCharges:
    stt_groups: tuple[SttGroup, ...]
    orders: tuple[tuple[str, ChargeBreakdown], ...]  # per order; their stt field is NOT used in totals
    dp: Decimal
    non_stt: Decimal  # brokerage + exchange + SEBI + IPFT + stamp + GST over all orders
    stt: Decimal
    total: Decimal
    assumptions: tuple[str, ...] = DAY_ASSUMPTIONS


def stt_group(schedule: ChargeSchedule, key, fills) -> SttGroup:
    d, exchange, isin, kind, side = key
    qty = sum(f.quantity for f in fills)
    turnover = sum((f.price * f.quantity for f in fills), D("0"))
    avg = _r(turnover / qty)
    stt = round_rupee(avg * qty * schedule.stt_pct[(kind, side)] / 100)
    return SttGroup(d, exchange, isin, kind, side, qty, turnover, avg, stt)


def day_charges(schedule: ChargeSchedule, fills) -> DayCharges:
    """Statutory and broker charges for a set of executed fills, aggregated the way the bill is built.

    Per order: brokerage (cap per executed order), exchange, SEBI, IPFT, stamp, GST. Per exchange/ISIN/
    day/kind/side: STT rounded to the rupee. Per ISIN and sell date (delivery only): one DP charge.
    """
    fills = list(fills)
    if not fills:
        raise ValueError("No fills")
    for f in fills:
        if f.quantity <= 0 or f.price <= 0:
            raise ValueError("price and quantity must be positive")
    orders: dict[str, list[Fill]] = {}
    for f in fills:
        orders.setdefault(f.order_id, []).append(f)
    order_rows = []
    for oid, group in sorted(orders.items()):
        first = group[0]
        if any((g.trade_date, g.exchange, g.isin, g.kind, g.side) != (first.trade_date, first.exchange, first.isin,
                                                                       first.kind, first.side) for g in group):
            raise ValueError(f"Order {oid} mixes dates, securities, kinds or sides")
        turnover = sum((g.price * g.quantity for g in group), D("0"))
        order_rows.append((oid, order_charges(schedule, exchange=first.exchange, kind=first.kind, side=first.side,
                                              price=turnover, quantity=1, trade_date=first.trade_date,
                                              bse_group=first.bse_group)))
    keyed: dict[tuple, list[Fill]] = {}
    for f in fills:
        keyed.setdefault((f.trade_date, f.exchange, f.isin, f.kind, f.side), []).append(f)
    groups = tuple(stt_group(schedule, k, v) for k, v in sorted(keyed.items(), key=lambda kv: tuple(map(str, kv[0]))))
    sell_days = {(f.isin, f.trade_date) for f in fills if f.kind is TradeKind.DELIVERY and f.side is Side.SELL}
    dp = dp_charges(schedule, sell_days)
    non_stt = sum((c.total - c.stt for _, c in order_rows), D("0"))
    stt = sum((g.stt for g in groups), D("0"))
    return DayCharges(groups, tuple(order_rows), dp, non_stt, stt, non_stt + stt + dp)


def reconcile_dp(expected_by_date: dict[date, Decimal], statement_by_date: dict[date, Decimal]) -> dict:
    """Compare expected DP charges with DP debits from the owner's funds statement, per posting date.

    The statement is the authority (DP is not on the contract note). Returns matched dates and
    differences; nothing is adjusted automatically.
    """
    dates = sorted(set(expected_by_date) | set(statement_by_date))
    rows = [{"date": d, "expected": expected_by_date.get(d, D("0")), "statement": statement_by_date.get(d, D("0"))}
            for d in dates]
    for r in rows:
        r["difference"] = r["statement"] - r["expected"]
    return {"matched": all(r["difference"] == 0 for r in rows), "rows": rows}
