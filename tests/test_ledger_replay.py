"""Ledger invariants under random event sequences, and replay behaviour (rejections, duplicates, restart)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from marketlab.ledger import Book, Fill, InterestConvention
from marketlab.ledger.book import FUNDED, HOLDINGS
from marketlab.ledger.demo import scenario
from marketlab.ledger.replay import load_events, replay, save_events
from marketlab.rules import IST, Exchange, MarketCalendar, Product, Side
from marketlab.rules.charges import ZERODHA_2026_11_04

CAL = MarketCalendar()
DAYS = [d for d in (date(2026, 11, 4) + timedelta(n) for n in range(45)) if CAL.is_trading_day(Exchange.NSE, d)]
ISINS = ["INE000P00011", "INE000P00022"]

op = st.tuples(
    st.sampled_from(["buy", "sell", "eod", "split"]),
    st.sampled_from([Product.CNC, Product.MTF]),
    st.sampled_from(ISINS),
    st.integers(1, 40),
    st.integers(1000, 20000).map(lambda x: D(x) * D("0.05")),  # Rs 50.00 .. 1000.00 on a 0.05 grid
    st.sampled_from([D("20"), D("25"), D("33.5"), D("50"), D("100")]),
)
programs = st.lists(st.tuples(st.integers(0, len(DAYS) - 1), op), min_size=1, max_size=40)


def run_program(program, conv):
    b = Book(CAL, ZERODHA_2026_11_04, conv)
    b.deposit(datetime(2026, 11, 4, 9, tzinfo=IST), D("10000000"))
    marks: dict[str, D] = {}
    n = 0
    for day_i, (kind, product, isin, qty, price, margin) in sorted(program, key=lambda x: x[0]):
        d = DAYS[day_i]
        at = datetime(d.year, d.month, d.day, 11, tzinfo=IST)
        n += 1
        if kind == "buy":
            b.buy(Fill(f"F{n}", at, Exchange.NSE, isin, product, Side.BUY, qty, price,
                       margin_pct=margin if product is Product.MTF else None))
            marks[isin] = price
        elif kind == "sell":
            held = sum(lot.qty for lot in b.lots(isin, product))
            if held:
                b.sell(Fill(f"F{n}", at, Exchange.NSE, isin, product, Side.SELL, min(qty, held), price))
                marks[isin] = price
        elif kind == "split":  # 2-for-1 is always a whole-share entitlement
            b.split(d, isin, 2, 1)
            if isin in marks:
                marks[isin] = (marks[isin] / 2).quantize(D("0.01"))
        else:
            marks[isin] = price
            b.end_of_day(d, dict(marks), {isin: margin})
    return b, marks


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(programs, st.sampled_from(list(InterestConvention)))
def test_invariants_hold_for_any_event_sequence(program, conv):
    b, marks = run_program(program, conv)
    j = b.journal
    assert j.trial_balance() == 0
    for e in j.entries:
        assert sum(p.amount for p in e.postings) == 0
    for product in (Product.CNC, Product.MTF):
        for isin in ISINS:
            lots = b.lots(isin, product)
            assert all(lot.qty >= 0 for lot in b.all_lots())
            assert j.balance(f"{HOLDINGS}{product}:{isin}") == sum((lot.cost for lot in lots), D("0"))
    for isin in ISINS:
        assert -j.balance(f"{FUNDED}{isin}") == sum((lot.funded for lot in b.lots(isin, Product.MTF)), D("0"))
    held = {lot.isin for lot in b.all_lots() if lot.qty}
    if held <= marks.keys():
        assert b.pnl_identity_gap(marks) == 0
    again, _ = run_program(program, conv)
    assert [e.postings for e in again.journal.entries] == [e.postings for e in j.entries]


# ------------------------------------------------------------------ replay

def _run(events):
    return replay(events, calendar=CAL, schedule=ZERODHA_2026_11_04,
                  account=dict(ddpi_enabled=True, resident_individual=True))


def test_demo_scenario_matches_fixtures_a_and_b():
    # DEMOEQ = fixture A (+173.32); DEMOFIN = fixture B, calendar days (+69.64); the margin
    # block/release in between moves no money out of the account. DEMOBE: 100 x 12.10 still held,
    # charges STT 1.21 + txn 0.04 + stamp 0.18 + GST 0.01 = 1.44 -> cash 10,000 + 173.32 + 69.64 - 1,211.44.
    res = _run(scenario())
    assert res.book.cash() == D("9031.52")
    assert {r.event_id: r.codes for r in res.rejected()} == {
        "E03": ("BROKER_MIS_BLOCKED", "MIS_NOT_ELIGIBLE", "POLICY_PRODUCT", "T2T_NO_INTRADAY"),
        "E04": ("MARKET_PROTECTION_REQUIRED",),
        "E08": ("INSUFFICIENT_SELLABLE_QTY", "T2T_NO_SAME_DAY_SELL"),
    }
    assert [r.outcome for r in res.records if r.event_id == "E13"] == ["APPLIED", "IGNORED_DUPLICATE"]


def test_rejected_order_has_no_ledger_effect():
    ev = scenario()
    only = [ev[0], ev[2]]  # deposit + the MIS order on a T2T stock
    b = _run(only).book
    assert [e.kind for e in b.journal.entries] == ["deposit"]


def test_restart_from_saved_log_is_identical(tmp_path):
    ev = scenario()
    first = _run(ev).book
    save_events(ev, tmp_path / "log.json")
    second = _run(load_events(tmp_path / "log.json")).book
    assert [(e.kind, e.postings) for e in second.journal.entries] == [(e.kind, e.postings) for e in first.journal.entries]


def test_insufficient_funds_is_a_rejection():
    ev = scenario()
    small = [dict(ev[0], amount="1000"), ev[1]]  # Rs 1,000 cannot buy 10 x 500
    res = _run(small)
    assert res.rejected()[0].codes == ("INSUFFICIENT_FUNDS",)
    assert [e.kind for e in res.book.journal.entries] == ["deposit"]


def test_fixture_fill_outside_limit_is_refused():
    ev = scenario()
    bad = [ev[0], dict(ev[1], fill_price="500.05")]  # buy limit 500.00 cannot fill higher
    with pytest.raises(ValueError):
        _run(bad)
