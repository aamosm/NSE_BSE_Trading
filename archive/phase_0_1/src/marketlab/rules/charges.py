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
    MTF = "MTF"


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
    mtf_pledge_fee: Decimal  # + GST, per pledge request per ISIN (once per buy day)
    mtf_unpledge_fee: Decimal  # + GST, per unpledge request per ISIN
    auto_square_off_fee: Decimal  # + GST, per order squared off by the broker's dealer
    cites: tuple[Cite, ...] = field(default=())


ZERODHA_2026_11_04 = ChargeSchedule(
    observed_on=date(2026, 11, 4),
    brokerage={
        TradeKind.DELIVERY: Brokerage(D("0"), None),
        TradeKind.INTRADAY: Brokerage(D("0.03"), D("20")),
        TradeKind.MTF: Brokerage(D("0.3"), D("20")),
    },
    stt_pct={
        (TradeKind.DELIVERY, Side.BUY): D("0.1"), (TradeKind.DELIVERY, Side.SELL): D("0.1"),
        (TradeKind.INTRADAY, Side.BUY): D("0"), (TradeKind.INTRADAY, Side.SELL): D("0.025"),
        (TradeKind.MTF, Side.BUY): D("0.1"), (TradeKind.MTF, Side.SELL): D("0.1"),
    },
    stamp_buy_pct={TradeKind.DELIVERY: D("0.015"), TradeKind.INTRADAY: D("0.003"), TradeKind.MTF: D("0.015")},
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
    mtf_pledge_fee=D("15"),
    mtf_unpledge_fee=D("15"),
    auto_square_off_fee=D("50"),
    cites=(
        Cite(("ZERODHA/CHARGES",), Status.BROKER_OFFICIAL, "All rates as listed on 2026-11-04."),
        Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
             "MTF STT and stamp duty use the delivery rates (MTF is a delivery purchase); not stated explicitly."),
        Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
             "Per-component paisa rounding (half-up); GST on the unrounded base. Reconcile with contract notes."),
        Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
             "DP charge applied once per ISIN per sell date ('per scrip, irrespective of quantity')."),
        Cite(("ZERODHA/CHARGES",), Status.UNKNOWN,
             "Whether the Rs 20/order debit-balance surcharge applies to MTF-funded accounts is not determined."),
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
    """DP charge for delivery/MTF sells: one charge per (ISIN, sell date). Not charged on MIS."""
    return schedule.dp_charge_per_scrip_incl_gst * len(sell_days)
