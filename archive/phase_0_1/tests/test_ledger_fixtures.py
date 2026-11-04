"""Hand-worked accounting fixtures A-F (arithmetic shown in docs/PHASE_1_PLAN.md section 5)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from marketlab.ledger import Book, Fill, InterestConvention, LedgerError, LotStatus, MtfState, PledgeState
from marketlab.rules import IST, Exchange, MarketCalendar, Product, Side
from marketlab.rules.charges import ZERODHA_2026_11_04

ISIN = "INE000A00010"


def at(day: int, h: int = 10, m: int = 0) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=IST)


def book(conv: InterestConvention = InterestConvention.CALENDAR_DAYS) -> Book:
    return Book(MarketCalendar(), ZERODHA_2026_11_04, conv)


def fill(fid, day, side, qty, price, product=Product.CNC, margin=None, forced=False, isin=ISIN):
    return Fill(fid, at(day), Exchange.NSE, isin, product, side, qty, D(price), margin_pct=margin, forced=forced)


def expense(b: Book, name: str) -> D:
    return b.expenses().get(name, D("0"))


# ------------------------------------------------------------------ A. normal cash trade

def test_fixture_a_normal_cash_trade():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("A1", 4, Side.BUY, 10, "500.00"))
    assert b.available_cash() == D("4994.06")  # 10,000 - 5,000 - 5.94 (payable until 5 Nov)
    b.end_of_day(date(2026, 11, 5), {ISIN: D("500")})
    assert b.cash() == D("4994.06")
    b.sell(fill("A2", 9, Side.SELL, 10, "520.00"))
    b.end_of_day(date(2026, 11, 10), {})  # 10 Nov is a settlement holiday: nothing settles
    assert b.cash() == D("4994.06") and b.unsettled() == D("5179.26")
    b.end_of_day(date(2026, 11, 11), {})
    assert b.cash() == D("10173.32")
    assert b.realized_gross() == D("200.00")
    assert sum(b.expenses().values()) == D("26.68")  # 5.94 + 5.40 + 15.34
    assert expense(b, "dp") == D("15.34") and expense(b, "stt") == D("10.20") and expense(b, "stamp") == D("0.75")
    (rt,) = b.round_trips
    assert rt.net_pnl == D("173.32")
    assert b.journal.trial_balance() == 0


# ------------------------------------------------------------------ B. MTF across a weekend and holiday

@pytest.mark.parametrize("conv, interest, final_cash", [
    (InterestConvention.CALENDAR_DAYS, D("14.40"), D("10069.64")),  # 6, 7, 8, 9, 10, 11 Nov
    (InterestConvention.TRADING_DAYS, D("7.20"), D("10076.84")),  # 6, 9, 11 Nov
])
def test_fixture_b_mtf_weekend_holiday(conv, interest, final_cash):
    b = book(conv)
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("B1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    (lot,) = b.lots(ISIN, Product.MTF)
    assert (lot.funded, lot.initial_margin, lot.pledge) == (D("6000.00"), D("2000.00"), PledgeState.PLEDGE_PENDING)
    assert expense(b, "pledge") == D("15") and b.mtf_funded() == D("6000.00")
    b.end_of_day(date(2026, 11, 6), {ISIN: D("400")})
    assert b.cash() == D("7949.19")  # 10,000 - 2,000 - 33.11 - 17.70
    assert lot.pledge is PledgeState.PLEDGED
    assert b.accrued_interest() == D("2.40")  # 6 Nov opening balance 6,000 x 0.04%
    b.sell(fill("B2", 11, Side.SELL, 20, "410.00", Product.MTF))
    assert b.accrued_interest() == interest
    b.end_of_day(date(2026, 11, 11), {})
    assert b.accrued_interest() == 0 and expense(b, "mtf_interest") == interest  # debited at close-out
    b.end_of_day(date(2026, 11, 12), {})
    assert b.cash() == final_cash
    assert b.mtf_funded() == 0 and lot.status is LotStatus.CLOSED and lot.pledge is PledgeState.UNPLEDGED
    (rt,) = b.round_trips
    assert rt.gross_pnl == D("200.00")
    assert (rt.charges + rt.interest).quantize(D("0.01")) == D("115.96") + interest
    assert b.journal.trial_balance() == 0


def test_btst_mtf_pays_exactly_one_day_of_interest():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("BT1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.sell(fill("BT2", 6, Side.SELL, 20, "400.00", Product.MTF))  # FAQ: interest on the T+1 opening balance
    assert b.accrued_interest() == D("2.40")


# ------------------------------------------------------------------ C. several lots and a partial exit

def test_fixture_c_fifo_partial_exit():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("C1", 4, Side.BUY, 10, "100.00"))
    b.buy(fill("C2", 5, Side.BUY, 10, "110.00"))
    b.sell(fill("C3", 9, Side.SELL, 15, "120.00"))
    assert b.realized_gross() == D("250.00")
    (left,) = b.lots(ISIN, Product.CNC)
    assert (left.qty, left.cost, left.trade_date) == (5, D("550.00"), date(2026, 11, 5))
    assert sum(b.expenses().values()) == D("19.71")  # 1.19 + 1.31 + 1.87 + 15.34
    assert expense(b, "stamp") == D("0.32")  # 0.15 + 0.17 (0.165 rounds half-up)
    b.end_of_day(date(2026, 11, 11), {ISIN: D("120")})
    assert b.cash() == D("9680.29")
    assert b.nlv({ISIN: D("120")}) == D("10280.29")
    assert b.pnl_identity_gap({ISIN: D("120")}) == 0
    # attribution: closed slices carry 1.19 + half of 1.31 + all of 1.87 and 15.34
    total_attr = sum((rt.charges for rt in b.round_trips), D("0"))
    assert total_attr == D("19.055")
    assert [rt.quantity for rt in b.round_trips] == [10, 5]


# ------------------------------------------------------------------ D. margin change

def _d_setup(deposit: str) -> Book:
    b = book()
    b.deposit(at(4, 9), D(deposit))
    b.buy(fill("D1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.end_of_day(date(2026, 11, 6), {ISIN: D("380")}, {ISIN: D("40")})
    return b


def test_fixture_d1_margin_call_met_from_free_cash():
    b = _d_setup("10000")
    s = b.mtf_status(ISIN)
    assert s.requirement == D("3600.00")  # 0.40 x 8,000 + (8,000 - 7,600)
    assert (s.blocked, s.shortfall, s.state) == (D("1600.00"), D("0"), MtfState.FUNDED)
    assert b.cash() == D("6349.19")
    # price recovers to 400 and margin back to 25%: the extra block is released
    b.end_of_day(date(2026, 11, 9), {ISIN: D("400")}, {ISIN: D("25")})
    assert b.mtf_blocked() == 0 and b.cash() == D("7949.19")


def test_fixture_d2_margin_shortfall():
    b = _d_setup("2100")
    s = b.mtf_status(ISIN)
    assert (s.blocked, s.shortfall, s.state) == (D("49.19"), D("1550.81"), MtfState.MARGIN_SHORTFALL)
    assert b.cash() == 0


def test_missing_mark_makes_margin_state_unknown():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("U1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.end_of_day(date(2026, 11, 6), {})
    assert b.mtf_status(ISIN).state is MtfState.MARGIN_UNKNOWN


# ------------------------------------------------------------------ E. forced exit

def test_fixture_e_forced_exit_after_shortfall():
    b = _d_setup("2100")
    b.sell(fill("E1", 9, Side.SELL, 20, "370.00", Product.MTF, forced=True))
    assert expense(b, "square_off") == D("50") and b.realized_gross() == D("-600.00")
    (lot,) = [x for x in b.all_lots() if x.product is Product.MTF]
    assert lot.status is LotStatus.BROKER_LIQUIDATED
    b.end_of_day(date(2026, 11, 9), {})
    assert expense(b, "mtf_interest") == D("9.60") and b.mtf_blocked() == 0
    b.end_of_day(date(2026, 11, 11), {})
    assert b.cash() == D("1316.27")
    assert b.journal.trial_balance() == 0


# ------------------------------------------------------------------ F. corporate action

def test_fixture_f_split_equals_fixture_a():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("F1", 4, Side.BUY, 10, "500.00"))
    b.split(date(2026, 11, 9), ISIN, 2, 1)
    (lot,) = b.lots(ISIN, Product.CNC)
    assert (lot.qty, lot.cost, lot.trade_date) == (20, D("5000.00"), date(2026, 11, 4))
    b.sell(fill("F2", 11, Side.SELL, 20, "260.00"))
    b.end_of_day(date(2026, 11, 12), {})
    assert b.cash() == D("10173.32") and b.round_trips[0].net_pnl == D("173.32")


def test_fractional_split_entitlement_is_rejected():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("F3", 4, Side.BUY, 3, "500.00"))
    with pytest.raises(LedgerError):
        b.split(date(2026, 11, 9), ISIN, 3, 2)


# ------------------------------------------------------------------ conversion, dividends, guards

def test_mtf_to_cnc_conversion_pays_original_funded_amount():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("V1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.end_of_day(date(2026, 11, 6), {ISIN: D("450")})
    b.convert_mtf_to_cnc(at(9), ISIN, 20)
    # 7,949.19 - funded 6,000 - unpledge 17.70
    assert b.cash() == D("1931.49") and b.mtf_funded() == 0
    (cnc,) = b.lots(ISIN, Product.CNC)
    assert (cnc.qty, cnc.cost, cnc.trade_date) == (20, D("8000.00"), date(2026, 11, 5))
    assert b.accrued_interest() == D("9.60")  # 6-9 Nov; the conversion day counts like a sale day


def test_conversion_needs_cash():
    b = book()
    b.deposit(at(4, 9), D("2100"))
    b.buy(fill("V2", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    with pytest.raises(LedgerError):
        b.convert_mtf_to_cnc(at(9), ISIN, 20)


def test_dividend_is_income_not_contribution():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("X1", 4, Side.BUY, 10, "500.00"))
    assert b.cash_dividend(date(2026, 11, 9), ISIN, D("5")) == D("50.00")
    assert b.dividends() == D("50.00") and b.net_contributions() == D("10000")


def test_duplicate_fill_is_ignored_and_out_of_order_events_rejected():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    assert b.buy(fill("Z1", 4, Side.BUY, 10, "500.00")) is True
    snapshot = b.journal.entries
    assert b.buy(fill("Z1", 4, Side.BUY, 10, "500.00")) is False
    assert b.journal.entries == snapshot
    b.end_of_day(date(2026, 11, 6), {})
    with pytest.raises(LedgerError):
        b.buy(fill("Z2", 5, Side.BUY, 1, "500.00"))


def test_cannot_sell_more_than_held_or_book_mis():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("G1", 4, Side.BUY, 10, "500.00"))
    with pytest.raises(LedgerError):
        b.sell(fill("G2", 9, Side.SELL, 11, "500.00"))
    with pytest.raises(LedgerError):
        b.buy(fill("G3", 9, Side.BUY, 1, "500.00", Product.MIS))


# ------------------------------------------------------------------ gaps found by the mutation check

def test_friday_mtf_buy_accrues_from_monday_settlement_not_the_weekend():
    # Buy Fri 6 Nov, settles Mon 9 Nov; sell Wed 11 Nov. Calendar days 9, 10, 11 = 3 x 2.40 = 7.20.
    # Counting from the trade date would add Sat 7 and Sun 8 (12.00).
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("W1", 6, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.sell(fill("W2", 11, Side.SELL, 20, "400.00", Product.MTF))
    assert b.accrued_interest() == D("7.20")


def test_partial_mtf_exit_repays_funding_pro_rata():
    # Sell 5 of 20 on Mon 9 Nov at 410: funded 6,000 x 5/20 = 1,500 repaid, 4,500 stays funded.
    # Sell charges on 2,050: brokerage 6.15 (0.3%, under the Rs 20 cap) + STT 2.05 + txn 0.062935->0.06
    # + SEBI 0.00205->0.00 + GST 0.18 x 6.214987 = 1.1187->1.12 = 9.38; DP 15.34; unpledge 17.70.
    # Interest: 6-9 Nov on 6,000 (4 x 2.40) + 10-11 Nov on 4,500 (2 x 1.80) = 13.20.
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("P1", 5, Side.BUY, 20, "400.00", Product.MTF, D("25")))
    b.sell(fill("P2", 9, Side.SELL, 5, "410.00", Product.MTF))
    (lot,) = b.lots(ISIN, Product.MTF)
    assert (lot.qty, lot.cost, lot.funded, lot.initial_margin) == (15, D("6000.00"), D("4500.00"), D("1500.00"))
    assert lot.status is LotStatus.PARTIALLY_CLOSED and b.mtf_funded() == D("4500.00")
    assert b.realized_gross() == D("50.00")
    assert b.unsettled() == D("550.00") - D("9.38") - D("15.34") - D("17.70")
    b.advance_to(date(2026, 11, 11))
    assert b.accrued_interest() == D("13.20")


def test_dp_charge_is_once_per_isin_per_sell_day():
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("Q1", 4, Side.BUY, 10, "500.00"))
    b.sell(fill("Q2", 9, Side.SELL, 4, "510.00"))
    b.sell(fill("Q3", 9, Side.SELL, 6, "510.00"))
    assert expense(b, "dp") == D("15.34")
    b.buy(fill("Q4", 9, Side.BUY, 2, "500.00"))
    b.sell(fill("Q5", 11, Side.SELL, 2, "505.00"))
    assert expense(b, "dp") == D("30.68")  # a new sell day is a new charge


def test_unsettled_sale_proceeds_are_not_available_cash():
    # Conservative policy (docs/METRICS.md section 2): proceeds count only once settled.
    b = book()
    b.deposit(at(4, 9), D("10000"))
    b.buy(fill("R1", 4, Side.BUY, 10, "500.00"))
    b.sell(fill("R2", 9, Side.SELL, 10, "520.00"))
    assert b.available_cash() == D("4994.06") and b.unsettled() == D("5179.26")
