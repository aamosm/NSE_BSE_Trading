"""Independent review cases for aamosm/NSE_BSE_Trading commit 19d12dc.

Run with the repository's src directory on PYTHONPATH. These assertions describe
required behavior and intentionally fail against the reviewed commit.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from marketlab.ledger import Book, Fill, LedgerError
from marketlab.ledger.demo import EQ, FIN, ACCOUNT, _order
from marketlab.ledger.replay import replay
from marketlab.metrics.selection import probability_of_backtest_overfitting
from marketlab.rules import IST, Exchange, MarketCalendar, Product, Side
from marketlab.rules.charges import ZERODHA_2026_11_04 as FEES

ISIN = "INE000R00010"


def at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=IST)


def new_book():
    b = Book(MarketCalendar(), FEES)
    b.deposit(at(4, 9), D("10000"))
    return b


def fill(fid, day, side, qty, price="100.00", product=Product.CNC):
    return Fill(fid, at(day), Exchange.NSE, ISIN, product, side, qty, D(price),
                margin_pct=D("25") if product is Product.MTF else None)


def run(events):
    return replay(events, calendar=MarketCalendar(), schedule=FEES, account=ACCOUNT)


def deposit(amount="10000"):
    return dict(id="deposit", type="deposit", at=at(4, 9).isoformat(), amount=amount)


def checked_inst(template, day):
    return dict(template, as_of=date(2026, 11, day).isoformat(),
                surveillance=[], suspended=False, special_preopen_today=False,
                in_periodic_call_auction=False)


def order(eid, day, inst, side="BUY", product="CNC", qty=1, price="500.00", hour=10):
    return _order(eid, at(day, hour).isoformat(), inst, side, product, qty, price)


def test_r01_replay_preserves_and_rejects_stale_snapshot_date():
    inst = checked_inst(EQ, 3)
    result = run([deposit(), order("stale", 4, inst)])
    assert result.records[-1].outcome == "REJECTED", result.records[-1]
    assert "STALE_SNAPSHOT" in result.records[-1].codes


def test_r02_missing_security_status_is_unknown_not_safe():
    inst = checked_inst(EQ, 4)
    for field in ("surveillance", "suspended", "special_preopen_today", "in_periodic_call_auction"):
        inst.pop(field)
    result = run([deposit(), order("unknown", 4, inst)])
    assert result.records[-1].outcome == "REJECTED", result.records[-1]


def test_r03_mtf_sale_receipt_cannot_fund_second_same_day_purchase():
    other = dict(checked_inst(EQ, 9), base_price="400.00", ltp="400.00")
    events = [
        deposit("2500"),
        order("funded_buy", 5, checked_inst(FIN, 5), product="MTF", qty=20, price="400.00"),
        order("funded_sell", 9, checked_inst(FIN, 9), side="SELL", product="MTF", qty=20, price="400.00"),
        order("cash_buy_1", 9, other, price="400.00", hour=11),
        order("cash_buy_2", 9, other, price="400.00", hour=12),
    ]
    result = run(events)
    assert result.records[-2].outcome == "APPLIED"
    assert result.records[-1].outcome == "REJECTED", (
        result.records[-1], result.book.cash(), result.book.available_cash(), result.book.unsettled()
    )


def test_r04_unresolved_margin_shortfall_blocks_new_entry_after_deposit():
    other = dict(checked_inst(EQ, 9), base_price="400.00", ltp="400.00")
    events = [
        deposit("2100"),
        order("funded_buy", 5, checked_inst(FIN, 5), product="MTF", qty=20, price="400.00"),
        dict(id="margin_call", type="end_of_day", on="2026-11-06",
             marks={FIN["isin"]: "380"}, margin_pct={FIN["isin"]: "40"}),
        dict(id="topup", type="deposit", at=at(9, 9).isoformat(), amount="500"),
        order("new_entry", 9, other, price="400.00"),
    ]
    result = run(events)
    assert result.book.mtf_status(FIN["isin"]).shortfall > D("500")
    assert result.records[-1].outcome == "REJECTED", result.records[-1]


def test_r05_mtf_unpledge_fee_counts_distinct_purchase_days():
    b = new_book()
    b.buy(fill("buy_1", 4, Side.BUY, 10, product=Product.MTF))
    b.buy(fill("buy_2", 5, Side.BUY, 10, product=Product.MTF))
    b.sell(fill("sell", 9, Side.SELL, 20, product=Product.MTF))
    assert b.expenses()["unpledge"] == D("30.00"), b.expenses()


def test_r06_same_day_cnc_round_trip_is_blocked_or_charged_as_intraday():
    events = [
        deposit(),
        order("buy", 4, checked_inst(EQ, 4), qty=2, price="500.00"),
        order("sell", 4, checked_inst(EQ, 4), side="SELL", qty=2, price="500.00", hour=11),
    ]
    result = run(events)
    if result.records[-1].outcome == "REJECTED":
        return
    expenses = result.book.expenses()
    assert expenses.get("brokerage", D("0")) == D("0.60"), expenses
    assert expenses.get("dp", D("0")) == D("0"), expenses
    assert expenses.get("stt", D("0")) == D("0.25"), expenses


def test_r07_rejected_fractional_split_does_not_mutate_earlier_lots():
    b = new_book()
    b.buy(fill("even", 4, Side.BUY, 2))
    b.buy(fill("odd", 5, Side.BUY, 3))
    before = deepcopy(b.all_lots())
    with pytest.raises(LedgerError, match="fractional"):
        b.split(date(2026, 11, 9), ISIN, 1, 2)
    assert b.all_lots() == before, [(x.lot_id, x.qty) for x in b.all_lots()]


def test_r08_conversion_fee_is_in_closed_trade_pnl():
    b = new_book()
    b.buy(fill("buy", 5, Side.BUY, 20, "400.00", Product.MTF))
    b.convert_mtf_to_cnc(at(9), ISIN, 20)
    b.sell(fill("sell", 11, Side.SELL, 20, "400.00"))
    b.end_of_day(date(2026, 11, 12), {})
    actual_account_pnl = b.nlv({}) - b.net_contributions()
    closed_trade_pnl = sum((t.net_pnl for t in b.round_trips), D("0"))
    assert closed_trade_pnl == actual_account_pnl, (closed_trade_pnl, actual_account_pnl)


def test_r09_pbo_tied_oos_winners_are_not_ranked_above_median():
    # First split has a unique IS winner and all three OOS results equal.
    # All equal values are at the OOS median. The reverse split ranks trial 0 first.
    rows = [[.03, .02, .01], [.03, .02, .01], [.01, .01, .01], [.01, .01, .01]]
    result = probability_of_backtest_overfitting(rows, 2, metric=lambda xs: sum(xs) / len(xs))
    assert result.pbo == .5, result


def test_r10_budget_sunday_is_a_known_session():
    cal = MarketCalendar()
    day = date(2026, 2, 1)
    assert cal.is_trading_day(Exchange.NSE, day) or cal.is_special_session(Exchange.NSE, day)
