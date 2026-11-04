"""End-to-end order validation scenarios. Each asserts the exact blocking reasons, not just accept/reject."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from conftest import MIS_POLICY, ACCOUNT, NO_POSITION, eq_snapshot, fno_snapshot, ist, order
from marketlab.rules import (
    AccountState,
    Exchange,
    Framework,
    OrderType,
    Outcome,
    Policy,
    PositionState,
    Product,
    Side,
    SurveillanceFlag,
    Validity,
    evaluate_order,
)


def run(o, inst=None, pos=NO_POSITION, acct=ACCOUNT, policy=None, cal=None):
    from marketlab.rules import MarketCalendar
    return evaluate_order(o, inst or eq_snapshot(), pos, acct, calendar=cal or MarketCalendar(), policy=policy)


def blocks(dec):
    return dec.codes(Outcome.BLOCK)


# ---- baseline -----------------------------------------------------------------------------------

def test_plain_cnc_limit_buy_is_accepted():
    dec = run(order())
    assert dec.accepted, dec.explain()
    assert dec.session == "CONTINUOUS"
    assert dec.effective_limit_price == D("201.00")


def test_decision_is_deterministic():
    assert run(order()) == run(order())


def test_shape_policy_and_staleness():
    assert "QUANTITY_INVALID" in blocks(run(order(quantity=0)))
    assert "TAG_INVALID" in blocks(run(order(tag="bad tag!")))
    assert "POLICY_PRODUCT" in blocks(run(order(product=Product.MIS)))  # MIS outside default scope
    assert "STALE_SNAPSHOT" in blocks(run(order(), eq_snapshot(as_of=date(2026, 11, 3))))


def test_holiday_weekend_and_unloaded_calendars():
    hol = run(order(submitted_at=ist(2026, 11, 10, 10, 0)), eq_snapshot(as_of=date(2026, 11, 10)))
    assert "MARKET_HOLIDAY" in blocks(hol)
    muhurat = run(order(submitted_at=ist(2026, 11, 8, 18, 0)), eq_snapshot(as_of=date(2026, 11, 8)))
    assert "SESSION_UNKNOWN" in blocks(muhurat)
    bse = run(order(exchange=Exchange.BSE), eq_snapshot(exchange=Exchange.BSE, series="A", tick_size=D("0.01")))
    assert "SESSION_UNKNOWN" in blocks(bse)


def test_series_classification():
    assert "SERIES_UNKNOWN" in blocks(run(order(), eq_snapshot(series="XX")))
    assert "SERIES_OUT_OF_SCOPE" in blocks(run(order(), eq_snapshot(series="SM")))


# ---- tick and band ------------------------------------------------------------------------------

def test_tick_size_depends_on_price():
    hi = dict(base_price=D("1500.00"), tick_reference_price=D("1490.00"), ltp=D("1501.00"))
    assert "PRICE_NOT_ON_TICK" in blocks(run(order(price=D("1500.05")), eq_snapshot(**hi)))  # tick 0.10
    assert run(order(price=D("1500.10")), eq_snapshot(**hi)).accepted
    assert run(order(price=D("201.01"))).accepted  # below 250: tick 0.01


def test_band_edges():
    assert run(order(price=D("240.00"))).accepted
    assert "PRICE_OUTSIDE_BAND" in blocks(run(order(price=D("240.01"))))
    assert "PRICE_OUTSIDE_BAND" in blocks(run(order(price=D("159.99"))))


def test_security_file_tick_wins_with_warning():
    dec = run(order(price=D("201.01")), eq_snapshot(tick_size=D("0.05")))
    assert "TICK_SOURCE_MISMATCH" in dec.codes(Outcome.WARN)
    assert "PRICE_NOT_ON_TICK" in blocks(dec)


def test_unknown_price_inputs_block():
    assert "BASE_PRICE_UNKNOWN" in blocks(run(order(), eq_snapshot(base_price=None)))
    assert "PRICE_BAND_UNKNOWN" in blocks(run(order(), eq_snapshot(price_band_pct=None)))
    assert "TICK_SIZE_UNKNOWN" in blocks(run(order(), eq_snapshot(tick_reference_price=None)))
    assert {"FNO_STATUS_UNKNOWN", "SESSION_UNKNOWN"} <= blocks(run(order(), eq_snapshot(has_derivatives=None)))


def test_fno_stock_uses_dynamic_operating_range():
    dec = run(order(price=D("1650.00")), fno_snapshot())
    assert dec.accepted and "DYNAMIC_BAND_ASSUMED" in dec.codes(Outcome.WARN)
    assert "PRICE_OUTSIDE_BAND" in blocks(run(order(price=D("1650.10")), fno_snapshot()))


# ---- trade-for-trade, BTST, same-day --------------------------------------------------------------

def be(**kw):
    return eq_snapshot(series="BE", **kw)


def test_t2t_cannot_be_traded_intraday():
    dec = run(order(product=Product.MIS), be(), policy=MIS_POLICY)
    assert {"T2T_NO_INTRADAY", "BROKER_MIS_BLOCKED"} <= blocks(dec)


def test_t2t_shares_bought_today_cannot_be_sold_today():
    dec = run(order(side=Side.SELL), be(), pos=PositionState(bought_today_qty=10))
    assert {"INSUFFICIENT_SELLABLE_QTY", "T2T_NO_SAME_DAY_SELL"} <= blocks(dec)


def test_t2t_next_day_sale_is_conservatively_blocked_until_verified():
    dec = run(order(side=Side.SELL), be(), pos=PositionState(t1_qty=10))
    assert "T2T_NEXT_DAY_SALE_UNVERIFIED" in blocks(dec)
    lenient = Policy(allow_unverified_t2t_next_day_sale=True)
    assert run(order(side=Side.SELL), be(), pos=PositionState(t1_qty=10), policy=lenient).accepted


def test_t2t_settled_shares_can_be_sold():
    assert run(order(side=Side.SELL), be(), pos=PositionState(settled_qty=10)).accepted


def test_btst_allowed_on_normal_day_with_risk_warning():
    dec = run(order(side=Side.SELL), pos=PositionState(t1_qty=10))
    assert dec.accepted and "BTST_SHORT_DELIVERY_RISK" in dec.codes(Outcome.WARN)


def test_btst_blocked_on_settlement_only_holiday():
    d = date(2026, 8, 26)  # exchange open, settlement holiday
    dec = run(order(side=Side.SELL, submitted_at=ist(2026, 8, 26, 10, 0)), eq_snapshot(as_of=d),
              pos=PositionState(t1_qty=10))
    assert "BTST_NOT_ALLOWED" in blocks(dec)
    assert "CURRENT_BROKER_RULES_APPLIED_TO_PAST" in dec.codes(Outcome.WARN)


def test_same_day_reversal_of_delivery_buy_warns_about_intraday_charges():
    dec = run(order(side=Side.SELL), pos=PositionState(bought_today_qty=10))
    assert dec.accepted and "INTRADAY_REVERSAL_OF_DELIVERY" in dec.codes(Outcome.WARN)


def test_naked_short_sale_is_blocked():
    assert "INSUFFICIENT_SELLABLE_QTY" in blocks(run(order(side=Side.SELL)))
    assert "INSUFFICIENT_SELLABLE_QTY" in blocks(
        run(order(side=Side.SELL), pos=PositionState(settled_qty=10, pending_sell_qty=5)))


# ---- surveillance ---------------------------------------------------------------------------------

def gsm(stage, **kw):
    return eq_snapshot(series="BE", base_price=D("20.00"), price_band_pct=D("5"), tick_reference_price=D("20.00"),
                       ltp=D("20.10"), surveillance=frozenset({SurveillanceFlag(Framework.GSM, stage)}), **kw)


def test_gsm3_buy_blocked_and_only_on_first_trading_day():
    dec = run(order(price=D("20.50")), gsm(3))  # Wednesday
    assert {"BROKER_FRESH_BUY_BLOCKED", "ONCE_A_WEEK_TRADING"} <= blocks(dec)


def test_gsm3_existing_holding_can_be_sold_on_monday():
    mon = date(2026, 11, 9)
    dec = run(order(side=Side.SELL, price=D("19.50"), submitted_at=ist(2026, 11, 9, 10, 0)), gsm(3, as_of=mon),
              pos=PositionState(settled_qty=10))
    assert dec.accepted, dec.explain()


def test_gsm4_has_no_upward_movement():
    mon = date(2026, 11, 9)
    dec = run(order(side=Side.SELL, price=D("20.10"), submitted_at=ist(2026, 11, 9, 10, 0)), gsm(4, as_of=mon),
              pos=PositionState(settled_qty=10))
    assert "PRICE_OUTSIDE_BAND" in blocks(dec)  # upper limit equals base price 20.00


def test_surveillance_band_conflict_and_unknown_lists():
    bad = eq_snapshot(surveillance=frozenset({SurveillanceFlag(Framework.GSM, 1)}))  # band 20% > max 5%
    assert "SURVEILLANCE_BAND_CONFLICT" in blocks(run(order(), bad))
    assert "SURVEILLANCE_UNKNOWN" in blocks(run(order(), eq_snapshot(surveillance=None)))
    assert "SURVEILLANCE_RULE_UNKNOWN" in blocks(
        run(order(), eq_snapshot(surveillance=frozenset({SurveillanceFlag(Framework.GSM, 9)}))))


def test_esm2_is_call_auction_only():
    snap = eq_snapshot(series="BE", price_band_pct=D("2"),
                       surveillance=frozenset({SurveillanceFlag(Framework.ESM, 2)}))
    assert "CALL_AUCTION_OUT_OF_SCOPE" in blocks(run(order(), snap))


def test_suspension_and_unknown_status_flags():
    assert "SUSPENDED" in blocks(run(order(), eq_snapshot(suspended=True)))
    assert "SUSPENDED_STATUS_UNKNOWN" in blocks(run(order(), eq_snapshot(suspended=None)))


# ---- sessions: pre-open and closing auction --------------------------------------------------------

def test_preopen_order_types():
    assert run(order(submitted_at=ist(2026, 11, 4, 9, 3))).accepted
    mkt = run(order(submitted_at=ist(2026, 11, 4, 9, 6), order_type=OrderType.MARKET, price=None,
                    market_protection_pct=D("2")))
    assert {"ORDER_TYPE_NOT_ALLOWED_IN_SESSION", "POLICY_LIMIT_ONLY_IN_AUCTION"} <= blocks(mkt)
    assert "SESSION_NOT_ACCEPTING_ORDERS" in blocks(run(order(submitted_at=ist(2026, 11, 4, 9, 9))))
    ioc = run(order(submitted_at=ist(2026, 11, 4, 9, 3), validity=Validity.IOC))
    assert "VALIDITY_NOT_ALLOWED_IN_AUCTION" in blocks(ioc)


def test_closing_auction_for_fno_stock():
    cas = fno_snapshot(cas_reference_price=D("1500.00"))  # CAS band 1455.00-1545.00
    at = lambda hh, mm: ist(2026, 11, 4, hh, mm)  # noqa: E731
    assert "SESSION_NOT_ACCEPTING_ORDERS" in blocks(run(order(submitted_at=at(15, 16), price=D("1500.00")), cas))
    assert run(order(submitted_at=at(15, 21), price=D("1545.00")), cas).accepted
    assert "PRICE_OUTSIDE_BAND" in blocks(run(order(submitted_at=at(15, 21), price=D("1545.10")), cas))
    assert "CAS_REFERENCE_UNKNOWN" in blocks(run(order(submitted_at=at(15, 21), price=D("1500.00")), fno_snapshot()))
    sl = order(submitted_at=at(15, 21), order_type=OrderType.SL, price=D("1510.00"), trigger_price=D("1505.00"))
    assert "ORDER_TYPE_NOT_ALLOWED_IN_SESSION" in blocks(run(sl, cas))
    assert run(order(submitted_at=at(15, 26), price=D("1500.00")), cas).accepted
    mkt = order(submitted_at=at(15, 26), order_type=OrderType.MARKET, price=None, market_protection_pct=D("1"))
    assert "ORDER_TYPE_NOT_ALLOWED_IN_SESSION" in blocks(run(mkt, cas))
    assert "SESSION_NOT_ACCEPTING_ORDERS" in blocks(run(order(submitted_at=at(15, 29), price=D("1500.00")), cas))


def test_non_fno_stock_keeps_trading_until_1530():
    assert run(order(submitted_at=ist(2026, 11, 4, 15, 21))).accepted


# ---- market orders and protection ------------------------------------------------------------------

def mkt(**kw):
    return order(order_type=OrderType.MARKET, price=None, **kw)


def test_api_market_order_needs_explicit_protection():
    assert "MARKET_PROTECTION_REQUIRED" in blocks(run(mkt()))
    assert "MARKET_PROTECTION_REQUIRED" in blocks(run(mkt(market_protection_pct=D("0"))))
    assert "POLICY_EXPLICIT_PROTECTION" in blocks(run(mkt(market_protection_pct=D("-1"))))
    assert "POLICY_PROTECTION_TOO_WIDE" in blocks(run(mkt(market_protection_pct=D("10"))))


def test_protected_limit_prices():
    # BUY: 201 x 1.02 = 205.02 (MPP cap 207.03, band 240) -> 205.02
    assert run(mkt(market_protection_pct=D("2"))).effective_limit_price == D("205.02")
    # SELL: 201 x 0.98 = 196.98 (MPP floor 194.97, band 160) -> 196.98
    sell = run(mkt(side=Side.SELL, market_protection_pct=D("2")), pos=PositionState(settled_qty=10))
    assert sell.effective_limit_price == D("196.98")
    # Low price: LTP 40, 5% would be 42.00 but exchange MPP caps at 40 + 1.5 = 41.50
    low = eq_snapshot(base_price=D("40.00"), tick_reference_price=D("40.00"), ltp=D("40.00"))
    assert run(mkt(market_protection_pct=D("5")), low).effective_limit_price == D("41.50")


def test_market_order_needs_a_trade_today():
    dec = run(mkt(market_protection_pct=D("2")), eq_snapshot(ltp=None))
    assert "MARKET_ORDER_NO_TRADE_TODAY" in blocks(dec)


def test_stop_loss_limit_validation():
    ok = order(order_type=OrderType.SL, price=D("205.00"), trigger_price=D("202.00"))
    assert run(ok).accepted
    gap = order(order_type=OrderType.SL, price=D("208.10"), trigger_price=D("202.00"))  # 6.10 > 6.06
    assert "SL_TRIGGER_LIMIT_GAP" in blocks(run(gap))
    direction = order(order_type=OrderType.SL, price=D("205.00"), trigger_price=D("206.00"))
    assert "SL_TRIGGER_DIRECTION" in blocks(run(direction))
    low = eq_snapshot(base_price=D("40.00"), tick_reference_price=D("40.00"), ltp=D("39.80"))
    low_gap = order(order_type=OrderType.SL, price=D("41.60"), trigger_price=D("40.00"))  # 1.60 > 1.50
    assert "SL_TRIGGER_LIMIT_GAP" in blocks(run(low_gap, low))
    assert "TRIGGER_PRICE_MISSING" in blocks(run(order(order_type=OrderType.SL, price=D("205.00"))))


# ---- MIS ------------------------------------------------------------------------------------------

def test_mis_cutoffs_and_eligibility():
    fno_late = order(product=Product.MIS, submitted_at=ist(2026, 11, 4, 15, 13), price=D("1500.00"))
    assert "MIS_CUTOFF_PASSED" in blocks(run(fno_late, fno_snapshot(), policy=MIS_POLICY))
    assert run(order(product=Product.MIS, submitted_at=ist(2026, 11, 4, 15, 13)), policy=MIS_POLICY).accepted
    late = order(product=Product.MIS, submitted_at=ist(2026, 11, 4, 15, 25))
    assert "MIS_CUTOFF_PASSED" in blocks(run(late, policy=MIS_POLICY))
    assert "MIS_ELIGIBILITY_UNKNOWN" in blocks(run(order(product=Product.MIS), eq_snapshot(mis_eligible=None),
                                                   policy=MIS_POLICY))
    short = order(product=Product.MIS, side=Side.SELL)
    assert "POLICY_NO_SHORT_SELLING" in blocks(run(short, policy=MIS_POLICY))
    past = order(product=Product.MIS, submitted_at=ist(2026, 7, 15, 10, 0))
    assert "MIS_CUTOFF_UNKNOWN" in blocks(run(past, eq_snapshot(as_of=date(2026, 7, 15)), policy=MIS_POLICY))


def test_explanation_is_built_from_recorded_checks():
    text = run(order(price=D("240.01"))).explain()
    assert text.startswith("REJECTED") and "PRICE_OUTSIDE_BAND" in text and "160.00-240.00" in text


# ---- review finding R02: an omitted status field is unknown, never safe ------------------------

def test_r02_omitted_security_status_blocks_instead_of_defaulting_to_safe():
    from marketlab.rules import InstrumentSnapshot
    bare = InstrumentSnapshot(as_of=date(2026, 11, 4), exchange=Exchange.NSE, symbol="TESTEQ",
                              isin="INE000T00011", series="EQ", has_derivatives=False, base_price=D("200.00"),
                              price_band_pct=D("20"), tick_reference_price=D("198.40"), ltp=D("201.00"))
    codes = blocks(run(order(), bare))
    assert {"SURVEILLANCE_UNKNOWN", "SUSPENDED_STATUS_UNKNOWN", "SPECIAL_PREOPEN_OUT_OF_SCOPE_STATUS_UNKNOWN",
            "CALL_AUCTION_OUT_OF_SCOPE_STATUS_UNKNOWN"} <= codes


def test_r01_stale_snapshot_date_is_not_overwritten_or_accepted():
    # The engine compares the snapshot's own date with the order date; nothing may refresh it.
    assert "STALE_SNAPSHOT" in blocks(run(order(), eq_snapshot(as_of=date(2026, 11, 3))))
