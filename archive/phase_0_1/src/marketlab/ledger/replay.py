"""Deterministic replay of an event log through the rules engine and the book.

Events are plain JSON-compatible dicts, so a log can be saved and replayed after a restart with an
identical result. Each order is first judged by ``rules.engine.evaluate_order`` and a funds check; a
rejected order is recorded with its reason codes and has no ledger effect. Event ids are unique;
a repeated id (e.g. a duplicated broker update) is recorded as ignored.

Phase 1 scope: fills are given in the event (``fill_price``). Fill simulation is Phase 3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..rules.calendar import MarketCalendar
from ..rules.charges import ChargeSchedule, TradeKind, order_charges
from ..rules.engine import evaluate_order
from ..rules.mtf import mtf_margin_pct
from ..rules.types import (
    AccountState,
    Exchange,
    Framework,
    InstrumentSnapshot,
    OrderRequest,
    OrderType,
    Outcome,
    Policy,
    PositionState,
    Product,
    Side,
    SurveillanceFlag,
    Validity,
)
from .book import Book, Fill, InterestConvention

D = Decimal

_SNAPSHOT_DECIMALS = {"base_price", "price_band_pct", "tick_size", "tick_reference_price", "ltp", "dynamic_band_pct",
                      "cas_reference_price", "var_pct", "elm_pct"}


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    event_id: str
    kind: str
    outcome: str  # APPLIED, REJECTED, IGNORED_DUPLICATE
    codes: tuple[str, ...] = ()
    explanation: str = ""


@dataclass
class ReplayResult:
    book: Book
    records: list[ReplayRecord] = field(default_factory=list)

    def rejected(self) -> list[ReplayRecord]:
        return [r for r in self.records if r.outcome == "REJECTED"]


def _dt(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    if t.tzinfo is None:
        raise ValueError(f"timestamp {s!r} must carry a UTC offset")
    return t


def snapshot_from(d: dict[str, Any], as_of: date) -> InstrumentSnapshot:
    kw = dict(d)
    kw["as_of"] = as_of
    kw["exchange"] = Exchange(kw["exchange"])
    for k in _SNAPSHOT_DECIMALS & kw.keys():
        if kw[k] is not None:
            kw[k] = D(str(kw[k]))
    if "surveillance" in kw and kw["surveillance"] is not None:
        kw["surveillance"] = frozenset(SurveillanceFlag(Framework(f), int(s)) for f, s in kw["surveillance"])
    return InstrumentSnapshot(**kw)


def position_for(book: Book, isin: str, on: date) -> PositionState:
    """Rules-engine view of the holding, derived from the book's lots (same ISIN across exchanges)."""
    settled = t1 = today = 0
    for lot in book.lots(isin, Product.CNC):
        if lot.trade_date == on:
            today += lot.qty
        elif lot.settle_date <= on:
            settled += lot.qty
        else:
            t1 += lot.qty
    mtf = sum(lot.qty for lot in book.lots(isin, Product.MTF))
    return PositionState(settled_qty=settled, t1_qty=t1, bought_today_qty=today, mtf_qty=mtf)


def _required_cash(schedule: ChargeSchedule, inst: InstrumentSnapshot, product: Product, qty: int, price: Decimal,
                   on: date, margin_pct: Decimal | None) -> Decimal:
    kind = TradeKind.MTF if product is Product.MTF else TradeKind.DELIVERY
    ch = order_charges(schedule, exchange=inst.exchange, kind=kind, side=Side.BUY, price=price, quantity=qty,
                       trade_date=on, bse_group=inst.series if inst.exchange is Exchange.BSE else None).total
    value = price * qty
    if product is Product.MTF:
        pledge = (schedule.mtf_pledge_fee * (1 + schedule.gst_pct / 100)).quantize(D("0.01"))
        return (value * margin_pct / 100).quantize(D("0.01")) + ch + pledge
    return value + ch


def replay(events: list[dict[str, Any]], *, calendar: MarketCalendar, schedule: ChargeSchedule,
           policy: Policy | None = None, account: dict[str, Any] | None = None,
           interest_convention: InterestConvention = InterestConvention.CALENDAR_DAYS) -> ReplayResult:
    book = Book(calendar, schedule, interest_convention)
    res = ReplayResult(book)
    seen: set[str] = set()
    acct = account or {}
    for ev in events:
        eid, kind = ev["id"], ev["type"]
        if eid in seen:
            res.records.append(ReplayRecord(eid, kind, "IGNORED_DUPLICATE", ("DUPLICATE_EVENT_ID",)))
            continue
        seen.add(eid)
        if kind == "deposit":
            book.deposit(_dt(ev["at"]), D(ev["amount"]), eid)
        elif kind == "withdraw":
            book.withdraw(_dt(ev["at"]), D(ev["amount"]), eid)
        elif kind == "end_of_day":
            book.end_of_day(date.fromisoformat(ev["on"]),
                            {k: D(v) for k, v in ev.get("marks", {}).items()},
                            {k: D(v) for k, v in ev.get("margin_pct", {}).items()})
        elif kind == "split":
            book.split(date.fromisoformat(ev["on"]), ev["isin"], int(ev["new"]), int(ev["old"]))
        elif kind == "dividend":
            book.cash_dividend(date.fromisoformat(ev["on"]), ev["isin"], D(ev["per_share"]), eid)
        elif kind == "convert":
            book.convert_mtf_to_cnc(_dt(ev["at"]), ev["isin"], int(ev["quantity"]), eid)
        elif kind == "forced_exit":  # broker action: a fact, not our order, so no rules check
            book.sell(Fill(eid, _dt(ev["at"]), Exchange(ev["exchange"]), ev["isin"], Product.MTF, Side.SELL,
                           int(ev["quantity"]), D(ev["price"]), forced=True))
        elif kind == "order":
            res.records.append(_order(ev, book, schedule, calendar, policy, acct))
            continue
        else:
            raise ValueError(f"unknown event type {kind!r}")
        res.records.append(ReplayRecord(eid, kind, "APPLIED"))
    return res


def _order(ev: dict[str, Any], book: Book, schedule: ChargeSchedule, calendar: MarketCalendar,
           policy: Policy | None, acct: dict[str, Any]) -> ReplayRecord:
    eid = ev["id"]
    t = _dt(ev["at"])
    book.advance_to(t.date())  # settle/accrue up to the decision day before judging cash
    inst = snapshot_from(ev["instrument"], t.date())
    o = ev["order"]
    order = OrderRequest(
        submitted_at=t, exchange=inst.exchange, side=Side(o["side"]), product=Product(o["product"]),
        order_type=OrderType(o.get("order_type", "LIMIT")), quantity=int(o["quantity"]),
        price=D(o["price"]) if o.get("price") is not None else None,
        trigger_price=D(o["trigger_price"]) if o.get("trigger_price") is not None else None,
        validity=Validity(o.get("validity", "DAY")),
        market_protection_pct=D(o["market_protection_pct"]) if o.get("market_protection_pct") is not None else None,
        tag=o.get("tag"))
    mtf_exposure = sum((lot.cost for lot in book.all_lots() if lot.product is Product.MTF and lot.qty), D("0"))
    stock_exposure = sum((lot.cost for lot in book.lots(inst.isin, Product.MTF)), D("0"))
    account = AccountState(ddpi_enabled=acct.get("ddpi_enabled"), resident_individual=acct.get("resident_individual"),
                           mtf_total_exposure_inr=mtf_exposure, mtf_stock_exposure_inr=stock_exposure)
    dec = evaluate_order(order, inst, position_for(book, inst.isin, t.date()), account, calendar=calendar,
                         policy=policy)
    if not dec.accepted:
        return ReplayRecord(eid, "order", "REJECTED", tuple(sorted(dec.codes(Outcome.BLOCK))), dec.explain())
    fill_price = D(ev["fill_price"])
    limit = dec.effective_limit_price
    if limit is not None and ((order.side is Side.BUY and fill_price > limit)
                              or (order.side is Side.SELL and fill_price < limit)):
        raise ValueError(f"{eid}: fixture fill {fill_price} violates the effective limit {limit}")
    margin = None
    if order.product is Product.MTF and order.side is Side.BUY:
        margin = mtf_margin_pct(inst.var_pct, inst.elm_pct, bool(inst.has_derivatives))
    if order.side is Side.BUY:
        need = _required_cash(schedule, inst, order.product, order.quantity, fill_price, t.date(), margin)
        if need > book.available_cash():
            return ReplayRecord(eid, "order", "REJECTED", ("INSUFFICIENT_FUNDS",),
                                f"REJECTED: needs Rs {need}, available Rs {book.available_cash()}")
    f = Fill(eid, t, inst.exchange, inst.isin, order.product, order.side, order.quantity, fill_price,
             bse_group=inst.series if inst.exchange is Exchange.BSE else None, margin_pct=margin)
    (book.buy if order.side is Side.BUY else book.sell)(f)
    return ReplayRecord(eid, "order", "APPLIED", tuple(sorted(dec.codes(Outcome.WARN))), dec.explain())


def save_events(events: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(events, indent=1), encoding="utf-8")


def load_events(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))
