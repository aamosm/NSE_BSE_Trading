"""Replayable accounting demonstration: ``python -m marketlab.ledger.demo``.

Synthetic instruments and prices only. No broker is contacted, and fills are given in the events
(fill simulation is Phase 3). The run shows rule decisions (including rejections with no ledger
effect), a duplicate event being ignored, a restart from the saved event log reproducing the same
journal, the balanced ledger, MTF funding/interest/margin, and metrics from docs/METRICS.md.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal as D
from pathlib import Path

from ..metrics import (
    compound_return,
    cost_bps_of_turnover,
    max_drawdown,
    time_weighted_returns,
    trade_stats,
)
from ..rules import MarketCalendar
from ..rules.charges import ZERODHA_2026_11_04
from .book import Book, InterestConvention
from .replay import load_events, replay, save_events

EQ = dict(exchange="NSE", symbol="DEMOEQ", isin="INE000D00010", series="EQ", has_derivatives=False,
          base_price="500.00", price_band_pct="20", tick_reference_price="498.00", ltp="501.00", mis_eligible=True,
          mtf_eligible=True, var_pct="10", elm_pct="3", in_nifty500=True, surveillance=[])
FIN = dict(EQ, symbol="DEMOFIN", isin="INE000F00010", base_price="400.00", tick_reference_price="399.00",
           ltp="400.50")
BE = dict(EQ, symbol="DEMOBE", isin="INE000B00010", series="BE", base_price="12.00", price_band_pct="5",
          tick_reference_price="12.00", ltp="12.10", mis_eligible=False, mtf_eligible=False)


def _order(eid, at, inst, side, product, qty, price, fill=None, **extra):
    o = dict(side=side, product=product, quantity=qty, price=price, **extra)
    return dict(id=eid, type="order", at=at, instrument=inst, order=o, fill_price=fill or price)


def scenario() -> list[dict]:
    t = "2026-11-{:02d}T{}+05:30".format
    return [
        dict(id="E01", type="deposit", at=t(4, "09:05:00"), amount="10000"),
        _order("E02", t(4, "10:00:00"), EQ, "BUY", "CNC", 10, "500.00"),
        _order("E03", t(4, "10:05:00"), BE, "BUY", "MIS", 100, "12.10"),
        _order("E04", t(4, "10:10:00"), EQ, "BUY", "CNC", 1, None, fill="501.00", order_type="MARKET"),
        dict(id="E05", type="end_of_day", on="2026-11-04", marks={EQ["isin"]: "505.00"}),
        _order("E06", t(5, "10:00:00"), FIN, "BUY", "MTF", 20, "400.00"),
        _order("E07", t(5, "10:30:00"), BE, "BUY", "CNC", 100, "12.10"),
        _order("E08", t(5, "11:00:00"), BE, "SELL", "CNC", 100, "12.20"),
        dict(id="E09", type="end_of_day", on="2026-11-05",
             marks={EQ["isin"]: "510.00", FIN["isin"]: "402.00", BE["isin"]: "12.15"}),
        dict(id="E10", type="end_of_day", on="2026-11-06", margin_pct={FIN["isin"]: "40"},
             marks={EQ["isin"]: "512.00", FIN["isin"]: "380.00", BE["isin"]: "12.00"}),
        _order("E11", t(9, "10:00:00"), dict(EQ, base_price="512.00", ltp="515.00"), "SELL", "CNC", 10, "520.00"),
        dict(id="E12", type="end_of_day", on="2026-11-09",
             marks={FIN["isin"]: "395.00", BE["isin"]: "12.30"}),
        _order("E13", t(11, "10:00:00"), dict(FIN, base_price="395.00", ltp="409.00"), "SELL", "MTF", 20,
               "410.00"),
        _order("E13", t(11, "10:00:00"), dict(FIN, base_price="395.00", ltp="409.00"), "SELL", "MTF", 20,
               "410.00"),  # the same update delivered twice
        dict(id="E14", type="end_of_day", on="2026-11-11", marks={BE["isin"]: "12.40"}),
        dict(id="E15", type="end_of_day", on="2026-11-12", marks={BE["isin"]: "12.50"}),
    ]


ACCOUNT = dict(ddpi_enabled=True, resident_individual=True)
NAMES = {EQ["isin"]: "DEMOEQ", FIN["isin"]: "DEMOFIN", BE["isin"]: "DEMOBE"}


def run(events, conv=InterestConvention.CALENDAR_DAYS):
    return replay(events, calendar=MarketCalendar(), schedule=ZERODHA_2026_11_04, account=ACCOUNT,
                  interest_convention=conv)


def _statement(b: Book, marks: dict[str, D]) -> None:
    print(f"  Settled cash            Rs {b.cash():>10}")
    print(f"  Unsettled (net)         Rs {b.unsettled():>10}")
    print(f"  MTF margin blocked      Rs {b.mtf_blocked():>10}")
    print(f"  Holdings at market      Rs {b.market_value(marks):>10}  (cost {b.cost_of_open_lots()})")
    print(f"  MTF funded principal    Rs {b.mtf_funded():>10}")
    print(f"  Accrued MTF interest    Rs {b.accrued_interest():>10}")
    nlv = b.nlv(marks)
    exit_costs = b.estimated_exit_costs(marks)
    print(f"  Net liquidation (NLV)   Rs {nlv:>10}  | after estimated exit costs Rs {nlv - exit_costs}")
    print(f"  Contributions           Rs {b.net_contributions().quantize(D('0.01')):>10}")
    print(f"  Realised P&L (gross)    Rs {b.realized_gross():>10}")
    print(f"  Unrealised P&L          Rs {b.market_value(marks) - b.cost_of_open_lots():>10}")
    exp = b.expenses()
    print(f"  Costs, total            Rs {sum(exp.values()):>10}  = " + ", ".join(f"{k} {v}" for k, v in exp.items()))
    print(f"  P&L identity gap        Rs {b.pnl_identity_gap(marks)}   trial balance {b.journal.trial_balance()}")


def main() -> None:
    events = scenario()
    res = run(events)
    b = res.book

    print("== Decisions (rules engine + funds check; rejected orders change nothing)")
    for r in res.records:
        if r.kind == "order" or r.outcome != "APPLIED":
            print(f"  {r.event_id} {r.outcome:<17} {', '.join(r.codes)}")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.json"
        save_events(events, path)
        again = run(load_events(path)).book
    same = [e.postings for e in again.journal.entries] == [e.postings for e in b.journal.entries]
    print(f"\n== Restart: replaying the saved event log gives an identical journal: {same}")

    last_marks = {FIN["isin"]: D("410.00"), BE["isin"]: D("12.50"), EQ["isin"]: D("520.00")}
    print("\n== Statement after 12 Nov settlement")
    _statement(b, last_marks)

    print("\n== Open lots")
    for lot in b.all_lots():
        print(f"  {lot.lot_id} {NAMES[lot.isin]:<8} {lot.product} qty {lot.qty:>3}/{lot.orig_qty:<3} "
              f"cost {lot.cost:>9} bought {lot.trade_date} status {lot.status} pledge {lot.pledge}")

    print("\n== Journal")
    for e in b.journal.entries:
        legs = "; ".join(f"{p.account} {p.amount:+}" for p in e.postings)
        print(f"  #{e.entry_id:02d} {e.on} {e.kind:<18} {legs}")

    print("\n== MTF interest under each day-count convention (Zerodha does not state which applies)")
    for conv in InterestConvention:
        bk = run(events, conv).book
        print(f"  {conv:<14} interest Rs {bk.expenses().get('mtf_interest', D('0'))}, final cash Rs {bk.cash()}")

    print("\n== Metrics (docs/METRICS.md). Six sessions: illustrative, not evidence of anything")
    vals = [dv.nlv for dv in b.daily]
    flows = [D("0")] + [dv.external_flow for dv in b.daily[1:]]
    twr = time_weighted_returns(vals, flows)
    print(f"  Daily NLV: " + ", ".join(f"{dv.on.day} Nov {dv.nlv}" for dv in b.daily))
    print(f"  Time-weighted return {compound_return(twr):.4%}; max drawdown {max_drawdown(vals).depth:.4%}")
    s = trade_stats(b.round_trips)
    print(f"  Round trips {s.count}: gross Rs {s.gross_pnl}, charges Rs {s.charges.quantize(D('0.01'))}, "
          f"interest Rs {s.interest.quantize(D('0.01'))}, net Rs {s.net_pnl.quantize(D('0.01'))}, "
          f"win rate {s.win_rate:.0%}, cost share of gross {s.cost_share_of_gross:.0%}")
    print(f"  Turnover Rs {b.traded_value}; all costs = {cost_bps_of_turnover(sum(b.expenses().values()), b.traded_value):.1f}"
          " bps of turnover")
    print(f"  Sharpe/PSR not reported: {len(twr)} daily returns cannot support them (docs/METRICS.md section 6).")


if __name__ == "__main__":
    main()
