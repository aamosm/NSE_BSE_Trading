"""Cash (CNC) and MTF book: lots, T+1 settlement, itemised charges, MTF funding, interest, margin.

The book records facts: a fill is posted even if it was unwise. Whether an order *may* be placed is
decided beforehand by ``rules.engine.evaluate_order`` and the replay's funds check.

Accounting rules, assumptions and hand-worked fixtures: docs/PHASE_1_PLAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from ..metrics.trading import RoundTrip
from ..rules.calendar import MarketCalendar
from ..rules.charges import ChargeBreakdown, ChargeSchedule, TradeKind, order_charges
from ..rules.mtf import MTF_DAILY_INTEREST_PCT
from ..rules.provenance import Cite, Status
from ..rules.types import Exchange, Product, Side
from .journal import PAISA, ZERO, Journal, LedgerError, Posting

D = Decimal

CASH = "asset:cash"
BLOCKED = "asset:mtf_margin_blocked:"
HOLDINGS = "asset:holdings:"
SETTLEMENT = "asset:settlement:"
FUNDED = "liability:mtf_funded:"
INTEREST_ACCRUED = "liability:mtf_interest_accrued"
CONTRIBUTIONS = "equity:contributions"
WITHDRAWALS = "equity:withdrawals"
REALIZED = "income:realized:"
DIVIDENDS = "income:dividends"
EXPENSE = "expense:"
INTEREST_EXPENSE = "expense:mtf_interest"

LEDGER_CITES = (
    Cite(("ZERODHA/MTF-FAQ",), Status.BROKER_OFFICIAL,
         "Funded = purchase value - initial margin; 0.04%/day from T+1 until sold; BTST pays interest on the "
         "T+1 opening balance (so the sale day counts); conversion to CNC pays the original funded amount; "
         "MTM collected daily on losing positions vs buy price; square-off Rs 50 + GST per order."),
    Cite(("ZERODHA/MTF-FAQ",), Status.UNKNOWN,
         "Whether weekends/holidays accrue interest: both conventions implemented (InterestConvention)."),
    Cite(("ZERODHA/MTF-LEDGER",), Status.ASSUMPTION,
         "Interest debited when MTF exposure closes and at month start ('debited on specific dates')."),
    Cite(("ZERODHA/MTF-LEDGER",), Status.ASSUMPTION,
         "On a sale, funded principal is repaid pro-rata to the quantity sold ('buy value is reversed upon "
         "selling'); margin requirement = margin% x buy value + MTM loss."),
    Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
         "Each fill is one executed order; charges, DP, pledge and fees settle with the trade's settlement date."),
)


def _r(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


class InterestConvention(StrEnum):
    CALENDAR_DAYS = "CALENDAR_DAYS"  # every calendar day from settlement(T) through the sale date (default)
    TRADING_DAYS = "TRADING_DAYS"  # only regular trading days in that range


class PledgeState(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PLEDGE_PENDING = "PLEDGE_PENDING"
    PLEDGED = "PLEDGED"
    UNPLEDGED = "UNPLEDGED"


class LotStatus(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    CONVERTED_TO_CASH = "CONVERTED_TO_CASH"
    BROKER_LIQUIDATED = "BROKER_LIQUIDATED"


class MtfState(StrEnum):
    FUNDED = "FUNDED"
    MARGIN_SHORTFALL = "MARGIN_SHORTFALL"
    MARGIN_UNKNOWN = "MARGIN_UNKNOWN"  # no mark supplied for an open funded position


@dataclass(frozen=True, slots=True)
class Fill:
    """One executed order (Phase 1 treats each fill as a complete order execution)."""

    fill_id: str
    at: datetime
    exchange: Exchange
    isin: str
    product: Product
    side: Side
    quantity: int
    price: Decimal
    bse_group: str | None = None
    margin_pct: Decimal | None = None  # MTF buys: client-funded percent of value
    forced: bool = False  # broker square-off of an MTF position


@dataclass(slots=True)
class Lot:
    lot_id: str
    isin: str
    product: Product
    exchange: Exchange
    trade_date: date
    settle_date: date
    qty: int
    orig_qty: int
    cost: Decimal  # open cost, paisa-exact
    buy_charges: Decimal  # charges of the buy still attributable to the open quantity (unrounded)
    funded: Decimal = ZERO  # open broker-funded principal (MTF), paisa-exact
    initial_margin: Decimal = ZERO  # client margin paid for the open quantity (MTF)
    interest: Decimal = ZERO  # interest accrued on this lot's open quantity (unrounded)
    margin_pct: Decimal | None = None
    pledge: PledgeState = PledgeState.NOT_APPLICABLE
    status: LotStatus = LotStatus.OPEN
    bse_group: str | None = None  # BSE charges depend on the scrip group


@dataclass(frozen=True, slots=True)
class MtfStatus:
    isin: str
    quantity: int
    buy_value: Decimal
    market_value: Decimal | None
    funded: Decimal
    initial_margin: Decimal
    blocked: Decimal
    requirement: Decimal | None
    shortfall: Decimal
    state: MtfState


@dataclass(frozen=True, slots=True)
class DailyValue:
    on: date
    nlv: Decimal
    external_flow: Decimal  # deposits - withdrawals made that day (before trading)


def _alloc(amount: Decimal, part: int, whole: int) -> Decimal:
    """Paisa-rounded pro-rata share; the whole amount when the part is everything."""
    return amount if part == whole else _r(amount * part / whole)


@dataclass
class Book:
    calendar: MarketCalendar
    schedule: ChargeSchedule
    interest_convention: InterestConvention = InterestConvention.CALENDAR_DAYS
    journal: Journal = field(default_factory=Journal)
    round_trips: list[RoundTrip] = field(default_factory=list)
    daily: list[DailyValue] = field(default_factory=list)
    corporate_actions: list[str] = field(default_factory=list)
    traded_value: Decimal = Decimal("0")  # sum of buy and sell values (turnover, both sides)

    def __post_init__(self) -> None:
        self._lots: dict[tuple[str, Product], list[Lot]] = {}
        self._seen_fills: set[str] = set()
        self._day: date | None = None
        self._lot_seq = 0
        self._dp_days: set[tuple[str, date]] = set()
        self._pledge_days: set[tuple[str, date]] = set()
        self._unpledge_days: set[tuple[str, date]] = set()
        self._interest_cum = ZERO  # unrounded cumulative accrual
        self._interest_posted = ZERO  # cumulative accrual posted to the journal
        self._margin_now: dict[str, Decimal] = {}
        self._mtf_states: dict[str, MtfStatus] = {}
        self._flows: dict[date, Decimal] = {}

    # ------------------------------------------------------------------ day handling

    @property
    def today(self) -> date | None:
        return self._day

    def advance_to(self, d: date) -> None:
        """Open every calendar day up to ``d`` (settlements, pledge confirmations, interest accrual)."""
        self._ensure_day(d)

    def _ensure_day(self, d: date) -> None:
        if self._day is None:
            self._day = d
            self._open_day(d)
            return
        if d < self._day:
            raise LedgerError(f"event dated {d} after the book reached {self._day}: events must be in time order")
        while self._day < d:
            self._day += timedelta(days=1)
            self._open_day(self._day)

    def _open_day(self, d: date) -> None:
        """Start of day: month-start interest debit, settlement, pledge confirmation, interest accrual."""
        if d.day == 1:
            self._debit_interest(d, "month start")
        acct = f"{SETTLEMENT}{d.isoformat()}"
        bal = self.journal.balance(acct)
        if bal != 0:
            self.journal.post(d, "settlement", f"net settlement for {d}", [Posting(CASH, bal), Posting(acct, -bal)])
        for lots in self._lots.values():
            for lot in lots:
                if lot.pledge is PledgeState.PLEDGE_PENDING and lot.settle_date <= d:
                    lot.pledge = PledgeState.PLEDGED
        self._accrue_interest(d)

    def _accrue_interest(self, d: date) -> None:
        if self.interest_convention is InterestConvention.TRADING_DAYS and not self.calendar.is_trading_day(
                Exchange.NSE, d):
            return
        day_total = ZERO
        for lot in self._open_lots(product=Product.MTF):
            if lot.settle_date <= d and lot.funded > 0:
                amt = lot.funded * MTF_DAILY_INTEREST_PCT / 100
                lot.interest += amt
                day_total += amt
        if day_total == 0:
            return
        self._interest_cum += day_total
        target = _r(self._interest_cum)
        delta = target - self._interest_posted
        if delta:
            self.journal.post(d, "mtf_interest", f"MTF interest accrual for {d}",
                              [Posting(INTEREST_EXPENSE, delta), Posting(INTEREST_ACCRUED, -delta)])
            self._interest_posted = target

    def _debit_interest(self, d: date, why: str) -> None:
        accrued = -self.journal.balance(INTEREST_ACCRUED)
        if accrued > 0:
            self.journal.post(d, "mtf_interest_debit", f"MTF interest debited ({why})",
                              [Posting(INTEREST_ACCRUED, accrued), Posting(CASH, -accrued)])

    # ------------------------------------------------------------------ external flows

    def deposit(self, at: datetime, amount: Decimal, ref: str = "") -> None:
        if amount <= 0:
            raise LedgerError("deposit must be positive")
        d = at.date()
        self._ensure_day(d)
        self.journal.post(d, "deposit", "funds added", [Posting(CASH, amount), Posting(CONTRIBUTIONS, -amount)], ref)
        self._flows[d] = self._flows.get(d, ZERO) + amount

    def withdraw(self, at: datetime, amount: Decimal, ref: str = "") -> None:
        d = at.date()
        self._ensure_day(d)
        if amount <= 0 or amount > self.available_cash():
            raise LedgerError("withdrawal must be positive and within available cash")
        self.journal.post(d, "withdrawal", "funds withdrawn", [Posting(WITHDRAWALS, amount), Posting(CASH, -amount)],
                          ref)
        self._flows[d] = self._flows.get(d, ZERO) - amount

    # ------------------------------------------------------------------ trades

    def _kind(self, product: Product) -> TradeKind:
        if product is Product.CNC:
            return TradeKind.DELIVERY
        if product is Product.MTF:
            return TradeKind.MTF
        raise LedgerError("MIS (intraday) accounting is outside Phase 1 and outside the default policy")

    def _post_charges(self, d: date, settle_acct: str, ch: ChargeBreakdown, ref: str, memo: str) -> None:
        parts = [("brokerage", ch.brokerage), ("stt", ch.stt), ("exchange_txn", ch.exchange_txn), ("sebi", ch.sebi),
                 ("ipft", ch.ipft), ("stamp", ch.stamp), ("gst", ch.gst)]
        postings = [Posting(f"{EXPENSE}{name}", amt) for name, amt in parts if amt]
        if postings:
            postings.append(Posting(settle_acct, -ch.total))
            self.journal.post(d, "charges", memo, postings, ref)

    def _post_fee(self, d: date, credit_acct: str, name: str, fee: Decimal, ref: str, memo: str,
                  gst_included: bool = False) -> Decimal:
        fee = _r(fee)
        if gst_included:
            self.journal.post(d, name, memo, [Posting(f"{EXPENSE}{name}", fee), Posting(credit_acct, -fee)], ref)
            return fee
        gst = _r(fee * self.schedule.gst_pct / 100)
        self.journal.post(d, name, memo, [Posting(f"{EXPENSE}{name}", fee), Posting(f"{EXPENSE}gst", gst),
                                          Posting(credit_acct, -(fee + gst))], ref)
        return fee + gst

    def buy(self, fill: Fill) -> bool:
        """Post a buy. Returns False (and changes nothing) for an already-seen fill id."""
        if fill.side is not Side.BUY:
            raise LedgerError("buy() needs a BUY fill")
        if fill.fill_id in self._seen_fills:
            return False
        if fill.quantity <= 0 or fill.price <= 0:
            raise LedgerError("quantity and price must be positive")
        kind = self._kind(fill.product)
        d = fill.at.date()
        self._ensure_day(d)
        value = fill.price * fill.quantity
        if value != value.quantize(PAISA):
            raise LedgerError("price must be in paise")
        settle = self.calendar.settlement_date(fill.exchange, d)
        sacct = f"{SETTLEMENT}{settle.isoformat()}"
        hold = f"{HOLDINGS}{fill.product}:{fill.isin}"
        im = funded = ZERO
        if fill.product is Product.MTF:
            if fill.margin_pct is None or not 0 < fill.margin_pct <= 100:
                raise LedgerError("MTF buy needs a margin percent in (0, 100]")
            im = _r(value * fill.margin_pct / 100)
            funded = value - im
            postings = [Posting(hold, value), Posting(sacct, -im), Posting(f"{FUNDED}{fill.isin}", -funded)]
        else:
            postings = [Posting(hold, value), Posting(sacct, -value)]
        self.traded_value += value
        self.journal.post(d, "buy", f"{fill.product} buy {fill.quantity} {fill.isin} @ {fill.price}", postings,
                          fill.fill_id)
        ch = order_charges(self.schedule, exchange=fill.exchange, kind=kind, side=Side.BUY, price=fill.price,
                           quantity=fill.quantity, trade_date=d, bse_group=fill.bse_group)
        self._post_charges(d, sacct, ch, fill.fill_id, f"charges on buy {fill.fill_id}")
        buy_costs = ch.total
        if fill.product is Product.MTF and (fill.isin, d) not in self._pledge_days:
            self._pledge_days.add((fill.isin, d))
            buy_costs += self._post_fee(d, sacct, "pledge", self.schedule.mtf_pledge_fee, fill.fill_id,
                                        f"MTF pledge {fill.isin}")
        self._lot_seq += 1
        lot = Lot(f"L{self._lot_seq:04d}", fill.isin, fill.product, fill.exchange, d, settle, fill.quantity,
                  fill.quantity, value, buy_costs, funded, im, ZERO, fill.margin_pct,
                  PledgeState.PLEDGE_PENDING if fill.product is Product.MTF else PledgeState.NOT_APPLICABLE,
                  bse_group=fill.bse_group)
        self._lots.setdefault((fill.isin, fill.product), []).append(lot)
        if fill.product is Product.MTF:
            self._margin_now.setdefault(fill.isin, fill.margin_pct)
        self._seen_fills.add(fill.fill_id)
        return True

    def sell(self, fill: Fill) -> bool:
        """Post a sell, matched FIFO within (ISIN, product). Returns False for an already-seen fill id."""
        if fill.side is not Side.SELL:
            raise LedgerError("sell() needs a SELL fill")
        if fill.fill_id in self._seen_fills:
            return False
        if fill.quantity <= 0 or fill.price <= 0:
            raise LedgerError("quantity and price must be positive")
        if fill.forced and fill.product is not Product.MTF:
            raise LedgerError("forced exits are modelled for MTF positions only")
        kind = self._kind(fill.product)
        d = fill.at.date()
        self._ensure_day(d)
        lots = [lot for lot in self._lots.get((fill.isin, fill.product), []) if lot.qty > 0]
        if sum(lot.qty for lot in lots) < fill.quantity:
            raise LedgerError(f"selling {fill.quantity} {fill.isin} {fill.product} but the book holds less")
        proceeds = fill.price * fill.quantity
        settle = self.calendar.settlement_date(fill.exchange, d)
        sacct = f"{SETTLEMENT}{settle.isoformat()}"

        # charges for this order, then once-per-day fees
        ch = order_charges(self.schedule, exchange=fill.exchange, kind=kind, side=Side.SELL, price=fill.price,
                           quantity=fill.quantity, trade_date=d, bse_group=fill.bse_group)
        order_costs = ch.total
        if (fill.isin, d) not in self._dp_days:
            self._dp_days.add((fill.isin, d))
            order_costs += self._post_fee(d, sacct, "dp", self.schedule.dp_charge_per_scrip_incl_gst, fill.fill_id,
                                          f"DP charge {fill.isin} {d}", gst_included=True)
        if fill.product is Product.MTF and (fill.isin, d) not in self._unpledge_days:
            self._unpledge_days.add((fill.isin, d))
            order_costs += self._post_fee(d, sacct, "unpledge", self.schedule.mtf_unpledge_fee, fill.fill_id,
                                          f"MTF unpledge {fill.isin}")
        if fill.forced:
            order_costs += self._post_fee(d, sacct, "square_off", self.schedule.auto_square_off_fee, fill.fill_id,
                                          f"broker square-off {fill.isin}")

        remaining = fill.quantity
        cost_rel = funded_rel = ZERO
        for lot in lots:
            if remaining == 0:
                break
            q = min(remaining, lot.qty)
            c = _alloc(lot.cost, q, lot.qty)
            f_ = _alloc(lot.funded, q, lot.qty)
            im = _alloc(lot.initial_margin, q, lot.qty)
            buy_ch = lot.buy_charges * q / lot.qty
            intr = lot.interest * q / lot.qty
            self.round_trips.append(RoundTrip(
                isin=fill.isin, product=str(fill.product), entry_date=lot.trade_date, exit_date=d, quantity=q,
                entry_value=c, exit_value=fill.price * q, charges=buy_ch + order_costs * q / fill.quantity,
                interest=intr, sessions_held=self._sessions_between(lot.trade_date, d)))
            lot.qty -= q
            lot.cost -= c
            lot.funded -= f_
            lot.initial_margin -= im
            lot.buy_charges -= buy_ch
            lot.interest -= intr
            if lot.qty == 0:
                lot.status = LotStatus.BROKER_LIQUIDATED if fill.forced else LotStatus.CLOSED
                if lot.product is Product.MTF:
                    lot.pledge = PledgeState.UNPLEDGED
            else:
                lot.status = LotStatus.PARTIALLY_CLOSED
            cost_rel += c
            funded_rel += f_
            remaining -= q
        gain = proceeds - cost_rel
        self.traded_value += proceeds
        postings = [Posting(sacct, proceeds - funded_rel), Posting(f"{HOLDINGS}{fill.product}:{fill.isin}", -cost_rel),
                    Posting(f"{REALIZED}{fill.product}", -gain)]
        if funded_rel:
            postings.append(Posting(f"{FUNDED}{fill.isin}", funded_rel))
        self.journal.post(d, "sell", f"{fill.product} sell {fill.quantity} {fill.isin} @ {fill.price}"
                          + (" (broker square-off)" if fill.forced else ""), postings, fill.fill_id)
        self._post_charges(d, sacct, ch, fill.fill_id, f"charges on sell {fill.fill_id}")
        self._seen_fills.add(fill.fill_id)
        return True

    def _sessions_between(self, start: date, end: date) -> int:
        n, cur = 0, start
        while cur < end:
            cur += timedelta(days=1)
            if self.calendar.is_trading_day(Exchange.NSE, cur):
                n += 1
        return n

    def convert_mtf_to_cnc(self, at: datetime, isin: str, quantity: int, ref: str = "") -> None:
        """Pay the original funded amount from available cash; lots become CNC (FIFO)."""
        d = at.date()
        self._ensure_day(d)
        lots = [lot for lot in self._lots.get((isin, Product.MTF), []) if lot.qty > 0]
        if quantity <= 0 or sum(lot.qty for lot in lots) < quantity:
            raise LedgerError("conversion quantity exceeds MTF holding")
        plan, remaining = [], quantity
        for lot in lots:
            if remaining == 0:
                break
            q = min(remaining, lot.qty)
            plan.append((lot, q))
            remaining -= q
        funded_total = sum((_alloc(lot.funded, q, lot.qty) for lot, q in plan), ZERO)
        fee = _r(self.schedule.mtf_unpledge_fee * (1 + self.schedule.gst_pct / 100))
        if funded_total + fee > self.available_cash():
            raise LedgerError("insufficient available cash to convert MTF to CNC")
        cost_total = ZERO
        for lot, q in plan:
            c, f_, im = _alloc(lot.cost, q, lot.qty), _alloc(lot.funded, q, lot.qty), _alloc(lot.initial_margin, q,
                                                                                            lot.qty)
            buy_ch, intr = lot.buy_charges * q / lot.qty, lot.interest * q / lot.qty
            self._lot_seq += 1
            self._lots.setdefault((isin, Product.CNC), []).append(Lot(
                f"L{self._lot_seq:04d}", isin, Product.CNC, lot.exchange, lot.trade_date, lot.settle_date, q, q, c,
                buy_ch, ZERO, ZERO, intr, None, PledgeState.NOT_APPLICABLE, bse_group=lot.bse_group))
            self._lots[(isin, Product.CNC)].sort(key=lambda x: (x.trade_date, x.lot_id))
            lot.qty -= q
            lot.cost -= c
            lot.funded -= f_
            lot.initial_margin -= im
            lot.buy_charges -= buy_ch
            lot.interest -= intr
            lot.status = LotStatus.CONVERTED_TO_CASH if lot.qty == 0 else LotStatus.PARTIALLY_CLOSED
            if lot.qty == 0:
                lot.pledge = PledgeState.UNPLEDGED
            cost_total += c
        self.journal.post(d, "mtf_conversion", f"convert {quantity} {isin} MTF to CNC",
                          [Posting(f"{HOLDINGS}CNC:{isin}", cost_total), Posting(f"{HOLDINGS}MTF:{isin}", -cost_total),
                           Posting(f"{FUNDED}{isin}", funded_total), Posting(CASH, -funded_total)], ref)
        if (isin, d) not in self._unpledge_days:
            self._unpledge_days.add((isin, d))
            self._post_fee(d, CASH, "unpledge", self.schedule.mtf_unpledge_fee, ref, f"MTF unpledge {isin}")

    # ------------------------------------------------------------------ corporate actions

    def split(self, on: date, isin: str, new: int, old: int) -> None:
        """Split or bonus (performance view): quantity x new/old, cost and funding unchanged."""
        if new <= 0 or old <= 0:
            raise LedgerError("split ratio must be positive")
        self._ensure_day(on)
        for (i, _), lots in self._lots.items():
            if i != isin:
                continue
            for lot in lots:
                if lot.qty == 0:
                    continue
                if (lot.qty * new) % old or (lot.orig_qty * new) % old:
                    raise LedgerError("fractional entitlement: cash-in-lieu is not modelled")
                lot.qty = lot.qty * new // old
                lot.orig_qty = lot.orig_qty * new // old
        self.corporate_actions.append(f"{on} {isin} split {new}:{old}")

    def cash_dividend(self, on: date, isin: str, per_share: Decimal, ref: str = "") -> Decimal:
        """Credit a dividend on the shares held now (call it on the record date). TDS is not modelled."""
        self._ensure_day(on)
        qty = sum(lot.qty for (i, _), lots in self._lots.items() if i == isin for lot in lots)
        amount = _r(per_share * qty)
        if amount:
            self.journal.post(on, "dividend", f"dividend {isin} {qty} x {per_share}",
                              [Posting(CASH, amount), Posting(DIVIDENDS, -amount)], ref)
        return amount

    # ------------------------------------------------------------------ end of day

    def end_of_day(self, on: date, marks: dict[str, Decimal] | None = None,
                   margin_pct: dict[str, Decimal] | None = None) -> None:
        """Apply marks and current MTF margin%, block/release margin, debit interest when MTF is flat."""
        self._ensure_day(on)
        marks = marks or {}
        self._margin_now.update(margin_pct or {})
        isins = {lot.isin for lot in self._open_lots(Product.MTF)}
        isins |= {a.removeprefix(BLOCKED) for a in self.journal.balances(BLOCKED)}
        for isin in sorted(isins):
            self._mtf_states[isin] = self._apply_margin(on, isin, marks.get(isin))
        if not any(True for _ in self._open_lots(Product.MTF)):
            self._debit_interest(on, "MTF exposure closed")
        held = {lot.isin for lot in self._open_lots()}
        if held <= set(marks):
            self.daily.append(DailyValue(on, self.nlv(marks), self._flows.get(on, ZERO)))

    def _apply_margin(self, on: date, isin: str, mark: Decimal | None) -> MtfStatus:
        lots = [lot for lot in self._lots.get((isin, Product.MTF), []) if lot.qty > 0]
        qty = sum(lot.qty for lot in lots)
        buy_value = sum((lot.cost for lot in lots), ZERO)
        funded = sum((lot.funded for lot in lots), ZERO)
        im = sum((lot.initial_margin for lot in lots), ZERO)
        acct = f"{BLOCKED}{isin}"
        blocked = self.journal.balance(acct)
        if qty and mark is None:
            return MtfStatus(isin, qty, buy_value, None, funded, im, blocked, None, ZERO, MtfState.MARGIN_UNKNOWN)
        mv = mark * qty if qty else ZERO
        pct = self._margin_now.get(isin, ZERO)
        requirement = _r(pct * buy_value / 100) + max(ZERO, buy_value - mv) if qty else ZERO
        need = max(ZERO, requirement - im)
        delta = need - blocked
        if delta > 0:
            take = min(delta, max(ZERO, self.available_cash()))
            if take:
                self.journal.post(on, "mtf_margin_block", f"additional MTF margin blocked {isin}",
                                  [Posting(acct, take), Posting(CASH, -take)])
            blocked += take
        elif delta < 0:
            self.journal.post(on, "mtf_margin_release", f"MTF margin released {isin}",
                              [Posting(CASH, -delta), Posting(acct, delta)])
            blocked += delta
        shortfall = max(ZERO, need - blocked)
        state = MtfState.MARGIN_SHORTFALL if shortfall > 0 else MtfState.FUNDED
        return MtfStatus(isin, qty, buy_value, mv if qty else None, funded, im, blocked, requirement, shortfall, state)

    # ------------------------------------------------------------------ reports

    def _open_lots(self, product: Product | None = None):
        for (_, p), lots in self._lots.items():
            if product is None or p is product:
                yield from (lot for lot in lots if lot.qty > 0)

    def lots(self, isin: str, product: Product) -> list[Lot]:
        return [lot for lot in self._lots.get((isin, product), []) if lot.qty > 0]

    def all_lots(self) -> list[Lot]:
        return [lot for lots in self._lots.values() for lot in lots]

    def cash(self) -> Decimal:
        return self.journal.balance(CASH)

    def unsettled(self) -> Decimal:
        """Net of all unsettled settlement obligations (positive = owed to us)."""
        return self.journal.total(SETTLEMENT)

    def available_cash(self) -> Decimal:
        """Settled cash minus unsettled payables. Unsettled sale proceeds are NOT counted (conservative)."""
        payables = sum((b for b in self.journal.balances(SETTLEMENT).values() if b < 0), ZERO)
        return self.cash() + payables

    def mtf_funded(self) -> Decimal:
        return -self.journal.total(FUNDED)

    def mtf_blocked(self) -> Decimal:
        return self.journal.total(BLOCKED)

    def accrued_interest(self) -> Decimal:
        return -self.journal.balance(INTEREST_ACCRUED)

    def mtf_status(self, isin: str) -> MtfStatus | None:
        return self._mtf_states.get(isin)

    def market_value(self, marks: dict[str, Decimal]) -> Decimal:
        return sum((marks[lot.isin] * lot.qty for lot in self._open_lots()), ZERO)

    def cost_of_open_lots(self) -> Decimal:
        return sum((lot.cost for lot in self._open_lots()), ZERO)

    def nlv(self, marks: dict[str, Decimal]) -> Decimal:
        """Net liquidation estimate BEFORE estimated exit costs (labelled; see nlv_after_exit_costs)."""
        return (self.cash() + self.unsettled() + self.mtf_blocked() + self.market_value(marks)
                - self.mtf_funded() - self.accrued_interest())

    def estimated_exit_costs(self, marks: dict[str, Decimal]) -> Decimal:
        total = ZERO
        by_key: dict[tuple[str, Product, Exchange, str | None], int] = {}
        for lot in self._open_lots():
            k = (lot.isin, lot.product, lot.exchange, lot.bse_group)
            by_key[k] = by_key.get(k, 0) + lot.qty
        isins = set()
        for (isin, product, exch, group), qty in by_key.items():
            total += order_charges(self.schedule, exchange=exch, kind=self._kind(product), side=Side.SELL,
                                   price=marks[isin], quantity=qty, trade_date=self._day or date.min,
                                   bse_group=group).total
            if isin not in isins:
                isins.add(isin)
                total += self.schedule.dp_charge_per_scrip_incl_gst
            if product is Product.MTF:
                total += _r(self.schedule.mtf_unpledge_fee * (1 + self.schedule.gst_pct / 100))
        return total

    def realized_gross(self) -> Decimal:
        return -self.journal.total(REALIZED)

    def expenses(self) -> dict[str, Decimal]:
        return {a.removeprefix(EXPENSE): b for a, b in self.journal.balances(EXPENSE).items()}

    def net_contributions(self) -> Decimal:
        return -self.journal.balance(CONTRIBUTIONS) - self.journal.balance(WITHDRAWALS)

    def dividends(self) -> Decimal:
        return -self.journal.balance(DIVIDENDS)

    def pnl_identity_gap(self, marks: dict[str, Decimal]) -> Decimal:
        """NLV - contributions - (realised + unrealised + dividends - expenses). Zero when consistent."""
        unrealized = self.market_value(marks) - self.cost_of_open_lots()
        explained = self.realized_gross() + unrealized + self.dividends() - sum(self.expenses().values(), ZERO)
        return self.nlv(marks) - self.net_contributions() - explained
