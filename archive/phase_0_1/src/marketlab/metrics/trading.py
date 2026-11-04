"""Trade-level, cost and execution metrics in rupees (Decimal). Definitions: docs/METRICS.md."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..rules.charges import PAISA, ChargeSchedule, TradeKind, order_charges
from ..rules.mtf import MTF_DAILY_INTEREST_PCT
from ..rules.types import Exchange, Side
from .performance import MetricUnavailable

D = Decimal
ZERO = D("0")


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """One closed position slice: quantity bought and later sold (FIFO-matched by the ledger)."""

    isin: str
    product: str  # CNC or MTF
    entry_date: date
    exit_date: date
    quantity: int
    entry_value: Decimal  # price x quantity, before charges
    exit_value: Decimal
    charges: Decimal  # all statutory/broker/DP/pledge charges allocated to this slice
    interest: Decimal = ZERO  # MTF interest allocated to this slice
    sessions_held: int = 0

    @property
    def gross_pnl(self) -> Decimal:
        return self.exit_value - self.entry_value

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.charges - self.interest


@dataclass(frozen=True, slots=True)
class TradeStats:
    count: int
    wins: int
    losses: int
    flat: int
    win_rate: float  # wins / count, on NET P&L
    gross_pnl: Decimal
    charges: Decimal
    interest: Decimal
    net_pnl: Decimal
    average_win: Decimal | None
    average_loss: Decimal | None  # negative number
    payoff_ratio: float | None  # average_win / |average_loss|
    profit_factor: float | None  # sum of net wins / |sum of net losses|
    expectancy: Decimal  # mean net P&L per round trip
    cost_share_of_gross: float | None  # (charges + interest) / |gross P&L|
    average_sessions_held: float


def trade_stats(trips: Sequence[RoundTrip]) -> TradeStats:
    if not trips:
        raise MetricUnavailable("no closed round trips")
    nets = [t.net_pnl for t in trips]
    win_v = [x for x in nets if x > 0]
    loss_v = [x for x in nets if x < 0]
    gross = sum((t.gross_pnl for t in trips), ZERO)
    charges = sum((t.charges for t in trips), ZERO)
    interest = sum((t.interest for t in trips), ZERO)
    avg_win = (sum(win_v, ZERO) / len(win_v)).quantize(PAISA) if win_v else None
    avg_loss = (sum(loss_v, ZERO) / len(loss_v)).quantize(PAISA) if loss_v else None
    return TradeStats(
        count=len(trips),
        wins=len(win_v),
        losses=len(loss_v),
        flat=len(trips) - len(win_v) - len(loss_v),
        win_rate=len(win_v) / len(trips),
        gross_pnl=gross,
        charges=charges,
        interest=interest,
        net_pnl=sum(nets, ZERO),
        average_win=avg_win,
        average_loss=avg_loss,
        payoff_ratio=float(avg_win / -avg_loss) if avg_win is not None and avg_loss is not None else None,
        profit_factor=float(sum(win_v, ZERO) / -sum(loss_v, ZERO)) if loss_v else None,
        expectancy=(sum(nets, ZERO) / len(trips)).quantize(PAISA),
        cost_share_of_gross=float((charges + interest) / abs(gross)) if gross else None,
        average_sessions_held=sum(t.sessions_held for t in trips) / len(trips),
    )


def turnover_ratio(traded_value: Decimal, average_equity: Decimal) -> float:
    """One-way turnover: sum of |buy and sell values| / 2 / average equity, for the measured period."""
    if average_equity <= 0:
        raise MetricUnavailable("average equity must be positive")
    return float(traded_value / 2 / average_equity)


def cost_bps_of_turnover(charges: Decimal, traded_value: Decimal) -> float:
    """Charges per rupee traded, in basis points."""
    if traded_value <= 0:
        raise MetricUnavailable("nothing traded")
    return float(charges / traded_value * 10000)


def slippage_bps(side: Side, decision_price: Decimal, fill_price: Decimal) -> float:
    """Implementation shortfall per share vs the decision price, in bps; positive = worse for us."""
    if decision_price <= 0:
        raise MetricUnavailable("decision price must be positive")
    signed = fill_price - decision_price if side is Side.BUY else decision_price - fill_price
    return float(signed / decision_price * 10000)


@dataclass(frozen=True, slots=True)
class BreakEven:
    entry_price: Decimal
    quantity: int
    exit_price: Decimal  # lowest paisa-grid exit price at which net P&L >= 0
    move_pct: Decimal  # (exit - entry) / entry x 100
    buy_charges: Decimal
    sell_charges: Decimal
    dp_charge: Decimal
    pledge_charge: Decimal  # pledge + unpledge, including GST
    interest: Decimal


def round_trip_breakeven(schedule: ChargeSchedule, *, exchange: Exchange, kind: TradeKind, price: Decimal,
                         quantity: int, trade_date: date, bse_group: str | None = None,
                         funded: Decimal = ZERO, interest_days: int = 0) -> BreakEven:
    """Smallest exit price (on a 1-paisa grid) that covers every cost of a buy-then-sell round trip.

    Includes the DP charge for delivery/MTF sells, the MTF pledge and unpledge fees (+GST) and simple MTF interest
    on ``funded`` for ``interest_days`` chargeable days. Tick-size rounding of the exit price is not
    applied, so this is a lower bound on the move actually needed.
    """
    if kind is TradeKind.INTRADAY and (funded or interest_days):
        raise MetricUnavailable("intraday round trips carry no MTF funding")
    buy = order_charges(schedule, exchange=exchange, kind=kind, side=Side.BUY, price=price,
                        quantity=quantity, trade_date=trade_date, bse_group=bse_group).total
    dp = schedule.dp_charge_per_scrip_incl_gst if kind is not TradeKind.INTRADAY else ZERO
    pledge = ((schedule.mtf_pledge_fee * (1 + schedule.gst_pct / 100)).quantize(PAISA)
              + (schedule.mtf_unpledge_fee * (1 + schedule.gst_pct / 100)).quantize(PAISA)) if kind is TradeKind.MTF else ZERO
    interest = (funded * MTF_DAILY_INTEREST_PCT / 100 * interest_days).quantize(PAISA)
    fixed = buy + dp + pledge + interest

    def net(p: Decimal) -> tuple[Decimal, Decimal]:
        sell = order_charges(schedule, exchange=exchange, kind=kind, side=Side.SELL, price=p,
                             quantity=quantity, trade_date=trade_date, bse_group=bse_group).total
        return (p - price) * quantity - fixed - sell, sell

    p = price
    deficit, sell = net(p)
    for _ in range(10000):
        if deficit >= 0:
            break
        step = max((-deficit / quantity).quantize(PAISA), PAISA)
        p += step
        deficit, sell = net(p)
    else:  # pragma: no cover - charges are a small fraction of turnover, so this converges quickly
        raise MetricUnavailable("break-even search did not converge")
    # Step back to the lowest paisa price that still breaks even.
    while p - PAISA > price and net(p - PAISA)[0] >= 0:
        p -= PAISA
        deficit, sell = net(p)
    return BreakEven(price, quantity, p, ((p - price) / price * 100).quantize(D("0.0001")),
                     buy, sell, dp, pledge, interest)
