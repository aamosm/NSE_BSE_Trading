"""Charges, MTF and Kite API rule tests. Each expected value is worked by hand in the comment."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from conftest import ist
from marketlab.rules import Exchange, RuleUnknown, Side
from marketlab.rules.broker import OrderRateLimiter, market_protection_valid, mis_cutoff, tag_valid
from marketlab.rules.charges import ZERODHA_2026_11_04 as Z
from marketlab.rules.charges import TradeKind, dp_charges, order_charges, with_gst
from marketlab.rules.mtf import mtf_interest_for_days, mtf_margin_pct, mtf_split, mtf_stock_cap

NOW = date(2026, 11, 4)


def charges(**kw):
    kw.setdefault("trade_date", NOW)
    kw.setdefault("exchange", Exchange.NSE)
    return order_charges(Z, **kw)


def test_nse_delivery_buy_10000():
    # turnover 10,000: STT 0.1% = 10.00; txn 0.00307% = 0.307 -> 0.31; SEBI 10/cr = 0.01; stamp 0.015% = 1.50
    # GST 18% x (0 + 0.307 + 0.01 + 0.00001) = 0.0570618 -> 0.06 ; total 11.88
    c = charges(kind=TradeKind.DELIVERY, side=Side.BUY, price=D("1000"), quantity=10)
    assert (c.brokerage, c.stt, c.exchange_txn, c.sebi, c.ipft, c.stamp, c.gst) == (
        D("0.00"), D("10.00"), D("0.31"), D("0.01"), D("0.00"), D("1.50"), D("0.06"))
    assert c.total == D("11.88")
    assert c.counterfactual is False


def test_nse_intraday_round_trip_50000():
    # buy: brokerage min(15, 20) = 15; txn 1.535 -> 1.54; SEBI 0.05; stamp 0.003% = 1.50
    # GST 18% x (15 + 1.535 + 0.05 + 0.00005) = 2.985309 -> 2.99 ; total 21.08
    b = charges(kind=TradeKind.INTRADAY, side=Side.BUY, price=D("500"), quantity=100)
    assert (b.brokerage, b.stt, b.exchange_txn, b.sebi, b.stamp, b.gst, b.total) == (
        D("15.00"), D("0.00"), D("1.54"), D("0.05"), D("1.50"), D("2.99"), D("21.08"))
    # sell: STT 0.025% = 12.50, no stamp ; total 15 + 12.50 + 1.54 + 0.05 + 2.99 = 32.08
    s = charges(kind=TradeKind.INTRADAY, side=Side.SELL, price=D("500"), quantity=100)
    assert (s.stt, s.stamp, s.total) == (D("12.50"), D("0.00"), D("32.08"))


def test_intraday_brokerage_cap():
    c = charges(kind=TradeKind.INTRADAY, side=Side.BUY, price=D("1000"), quantity=1000)  # 0.03% = 300 -> cap 20
    assert c.brokerage == D("20.00")


def test_mtf_buy_100000():
    # brokerage min(0.3% = 300, 20) = 20; STT 100.00; txn 3.07; SEBI 0.10; stamp 15.00
    # GST 18% x (20 + 3.07 + 0.10 + 0.0001) = 4.170618 -> 4.17 ; total 142.34
    c = charges(kind=TradeKind.MTF, side=Side.BUY, price=D("1000"), quantity=100)
    assert (c.brokerage, c.stt, c.exchange_txn, c.sebi, c.stamp, c.gst, c.total) == (
        D("20.00"), D("100.00"), D("3.07"), D("0.10"), D("15.00"), D("4.17"), D("142.34"))


def test_bse_group_transaction_charges_differ_sharply():
    # X group: Rs 10,000/crore = 0.1% -> 20.00 on 20,000; GST 18% x 20.02 = 3.6036 -> 3.60; total 43.62
    x = charges(exchange=Exchange.BSE, bse_group="X", kind=TradeKind.DELIVERY, side=Side.SELL,
                price=D("100"), quantity=200)
    assert (x.exchange_txn, x.gst, x.total) == (D("20.00"), D("3.60"), D("43.62"))
    # A group: 0.00375% -> 0.75; GST 18% x 0.77 = 0.1386 -> 0.14; total 20 + 0.75 + 0.02 + 0.14 = 20.91
    a = charges(exchange=Exchange.BSE, bse_group="A", kind=TradeKind.DELIVERY, side=Side.SELL,
                price=D("100"), quantity=200)
    assert (a.exchange_txn, a.gst, a.total) == (D("0.75"), D("0.14"), D("20.91"))
    with pytest.raises(ValueError):
        charges(exchange=Exchange.BSE, kind=TradeKind.DELIVERY, side=Side.SELL, price=D("100"), quantity=1)


def test_tiny_trade_rounding():
    # 1 share at 33.33: STT 0.03333 -> 0.03; stamp 0.0049995 -> 0.00; everything else rounds to 0.00
    c = charges(kind=TradeKind.DELIVERY, side=Side.BUY, price=D("33.33"), quantity=1)
    assert c.total == D("0.03")


def test_counterfactual_flag_for_past_dates():
    c = charges(kind=TradeKind.DELIVERY, side=Side.BUY, price=D("100"), quantity=1, trade_date=date(2025, 1, 2))
    assert c.counterfactual is True


def test_dp_and_pledge_fees():
    days = {("INE000T00011", NOW), ("INE000T00011", NOW), ("INE000T00011", date(2026, 11, 5))}
    assert dp_charges(Z, days) == D("30.68")  # set dedupes same ISIN/day: 2 x 15.34
    assert with_gst(Z, Z.mtf_pledge_fee) == D("17.70")  # 15 + 18% GST
    assert with_gst(Z, Z.auto_square_off_fee) == D("59.00")


@pytest.mark.parametrize("var,elm,fno,expected", [
    ("12.5", "3.5", True, "23.0"),   # 12.5 + 3 x 3.5
    ("12.5", "3.5", False, "30.0"),  # 12.5 + 5 x 3.5
    ("40", "15", False, "100"),      # 40 + 75 = 115 -> capped
])
def test_mtf_margin(var, elm, fno, expected):
    assert mtf_margin_pct(D(var), D(elm), fno) == D(expected)


def test_mtf_split_and_interest():
    client, funded = mtf_split(D("10000"), D("23"))
    assert (client, funded) == (D("2300"), D("7700"))
    assert mtf_interest_for_days(D("5000"), 30) == D("60")  # build guide's worked example
    assert mtf_interest_for_days(D("7700"), 1) == D("3.08")
    assert mtf_stock_cap(None) == D("30000000")  # unknown index membership -> strictest cap


def test_mis_cutoffs():
    from datetime import time
    assert mis_cutoff(NOW, True) == time(15, 12)
    assert mis_cutoff(NOW, False) == time(15, 25)
    with pytest.raises(RuleUnknown):
        mis_cutoff(date(2026, 7, 15), False)


@pytest.mark.parametrize("pct,ok", [(None, False), ("0", False), ("-1", True), ("0.5", True), ("100", True),
                                    ("100.01", False), ("-2", False)])
def test_market_protection_values(pct, ok):
    assert market_protection_valid(None if pct is None else D(pct)) is ok


def test_tag_rules():
    assert tag_valid(None) and tag_valid("abc123") and tag_valid("A" * 20)
    assert not tag_valid("A" * 21) and not tag_valid("bad tag") and not tag_valid("")


def test_rate_limiter_per_second_and_minute():
    lim = OrderRateLimiter()
    t0 = ist(2026, 11, 4, 10, 0)
    assert all(lim.try_acquire(t0 + timedelta(milliseconds=100 * i)) for i in range(10))
    assert not lim.try_acquire(t0 + timedelta(milliseconds=950))  # 11th inside the same second
    assert lim.try_acquire(t0 + timedelta(seconds=1))  # first one has aged out

    lim = OrderRateLimiter()
    sent = [lim.try_acquire(t0 + timedelta(milliseconds=150 * i)) for i in range(400)]  # <=7 per second
    assert all(sent)
    assert not lim.try_acquire(t0 + timedelta(milliseconds=59_900))  # 401st within 60 s
    assert lim.try_acquire(t0 + timedelta(seconds=60))  # first one aged out
