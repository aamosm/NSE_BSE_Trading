"""Single-instrument diagnostic baselines. Never presented as the final strategy."""
from __future__ import annotations

import csv
import hashlib
import statistics
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal as D
from pathlib import Path

from .common import money, timestamp
from .costs import OBSERVED_ON, total_charges


@dataclass(frozen=True)
class Bar:
    start: datetime
    end: datetime
    available_at: datetime
    open: D
    high: D
    low: D
    close: D
    volume: int

    def __post_init__(self):
        if timestamp(self.start) >= timestamp(self.end) or timestamp(self.available_at) < timestamp(self.end):
            raise ValueError("Bar timing is inconsistent")
        if not all(x.is_finite() and x > 0 for x in (self.open, self.high, self.low, self.close)):
            raise ValueError("OHLC values must be positive and finite")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close) or self.volume < 0:
            raise ValueError("Invalid OHLC or volume")


def load_bars(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        bars = [Bar(*(timestamp(r[k]) for k in ("start", "end", "available_at")),
                    *(D(r[k]) for k in ("open", "high", "low", "close")), int(r["volume"]))
                for r in csv.DictReader(f)]
    if len(bars) < 3:
        raise ValueError("At least three bars are required")
    if any(b.start >= c.start or b.end > c.start for b, c in zip(bars, bars[1:])):
        raise ValueError("Bars overlap, repeat, or are out of order")
    return bars


def baseline_signal(history, strategy, lookback):
    if strategy == "cash":
        return False
    if strategy == "buy_hold":
        return True
    if len(history) < lookback:
        return False
    prices = [b.close for b in history[-lookback:]]
    mean = sum(prices) / len(prices)
    if strategy == "trend":
        return prices[-1] > mean
    if strategy == "intraday_reversal":
        return prices[-1] < mean * D(".99")
    raise ValueError("Unknown baseline")


def simulate(bars, *, strategy="trend", initial_cash="10000", lookback=20,
             exchange="NSE", bse_group=None, slippage_bps=10, participation=.001,
             max_weight=.20, fixed_cost_inr="0"):
    if not bars or any(b.start >= c.start or b.end > c.start for b, c in zip(bars, bars[1:])):
        raise ValueError("Nonempty, ordered, non-overlapping bars required")
    if strategy not in {"cash", "buy_hold", "trend", "intraday_reversal"}:
        raise ValueError("Unknown baseline")
    if lookback < 2 or not 0 < max_weight <= 1 or not 0 < participation <= .01 or not 0 <= slippage_bps <= 1000:
        raise ValueError("Invalid research settings")
    initial, fixed = money(initial_cash), money(fixed_cost_inr)
    if initial <= 0 or fixed < 0:
        raise ValueError("Invalid initial cash or fixed cost")
    style = "intraday" if strategy == "intraday_reversal" else "delivery"
    cash, quantity, pending, costs = initial, 0, [], D("0")
    entry_date = None
    trades, decisions, curve = [], [], []
    dp_days = set()
    slip = D(str(slippage_bps)) / 10000
    # Execution uses only the previous completed bar for a volume participation cap.
    for i, bar in enumerate(bars):
        for release, amount in list(pending):
            if release <= bar.start:
                cash += amount
                pending.remove((release, amount))
        history = [x for x in bars[:i] if x.available_at <= bar.start]
        target = baseline_signal(history, strategy, lookback) if history else False
        reason = "BASELINE_LONG" if target else "BASELINE_CASH"
        if style == "intraday":
            if quantity and entry_date != bar.start.date():
                raise ValueError("Missing intraday exit bar; cannot assume an overnight fill")
            if bar.start.time() >= time(15, 5):
                target, reason = False, "SCHEDULED_INTRADAY_EXIT"
            elif bar.start.time() < time(9, 30) or bar.start.time() >= time(14, 45):
                target = bool(quantity)
        cap = int(history[-1].volume * participation) if history else 0
        traded = False
        if quantity and not target:
            if style == "delivery" and entry_date == bar.start.date():
                reason = "SAME_DAY_DELIVERY_NETTING_UNSUPPORTED"
            elif cap < quantity or bar.volume == 0:
                reason = "EXIT_NOT_FILLED_LIQUIDITY"
            else:
                px = money(bar.open * (1 - slip))
                value = px * quantity
                dp = (bar.start.date() not in dp_days)
                fees = total_charges(value, side="SELL", style=style, exchange=exchange, bse_group=bse_group, dp=dp)
                if style == "delivery":
                    # Conservative availability: next session represented in this dataset.
                    next_session = next((b.start for b in bars[i+1:] if b.start.date() > bar.start.date()), None)
                    if next_session is None:
                        next_session = datetime.max.replace(tzinfo=bar.start.tzinfo)
                    pending.append((next_session, value - fees))
                    dp_days.add(bar.start.date())
                else:
                    cash += value - fees
                trades.append({"at": str(bar.start), "side": "SELL", "qty": quantity, "price": str(px), "fees": str(fees), "reason": reason})
                costs += fees
                quantity, entry_date, traded = 0, None, True
        if not quantity and target and not traded:
            px = money(bar.open * (1 + slip))
            budget = min(cash, initial * D(str(max_weight)))
            q = min(int(budget / px), cap) if px > 0 and bar.volume > 0 else 0
            while q and px*q + total_charges(px*q, side="BUY", style=style, exchange=exchange, bse_group=bse_group) > budget:
                q -= 1
            if q:
                fees = total_charges(px*q, side="BUY", style=style, exchange=exchange, bse_group=bse_group)
                cash -= px*q + fees
                costs += fees
                quantity, entry_date = q, bar.start.date()
                trades.append({"at": str(bar.start), "side": "BUY", "qty": q, "price": str(px), "fees": str(fees), "reason": reason})
            else:
                reason = "ENTRY_NOT_FILLED_CASH_OR_LIQUIDITY"
        nav = cash + sum((x[1] for x in pending), D("0")) + bar.close * quantity
        curve.append({"at": str(bar.end), "nav": str(money(nav)), "cash": str(cash),
                      "unsettled": str(sum((x[1] for x in pending), D("0"))), "shares": quantity})
        decisions.append({"at": str(bar.start), "reason": reason, "known_bars": len(history),
                          "last_input_available_at": str(history[-1].available_at) if history else None})
        if cash < 0 or quantity < 0:
            raise AssertionError("Cash-only invariant broken")
    if style == "intraday" and quantity:
        raise ValueError("Dataset ended with an open intraday position; no invented final exit")
    navs = [initial] + [D(x["nav"]) for x in curve]
    peak, drawdown = initial, D("0")
    for x in navs:
        peak = max(peak, x)
        drawdown = max(drawdown, (peak-x)/peak)
    exit_estimate = total_charges(bars[-1].close*quantity, side="SELL", style=style, exchange=exchange,
                                 bse_group=bse_group, dp=True) if quantity else D("0")
    final = navs[-1] - fixed
    return {"mode": "DIAGNOSTIC_BACKTEST", "strategy": strategy, "initial_cash": str(initial),
            "final_marked_nav": str(final), "net_pnl_after_fixed_cost": str(final-initial),
            "estimated_exit_cost_on_open_position": str(exit_estimate),
            "final_nav_less_exit_estimate": str(final-exit_estimate),
            "fees": str(costs), "fixed_operating_cost": str(fixed), "max_drawdown_before_fixed_cost": float(drawdown),
            "trades": trades, "decisions": decisions, "equity_curve": curve, "live_orders": False,
            "limitations": [
                "Simple diagnostic baseline; no learned alpha or news signal.",
                "Current 2026-11-04 fees; historical use is a counterfactual.",
                "Per-order paise rounding is not contract-note reconciled.",
                "Next represented session settlement approximation; no holiday settlement file.",
                "No partial fills, queue position, circuit limits, auctions or corporate-action ledger.",
                "OHLC fill and previous-volume cap approximate executable prices.",
                "Open delivery positions are marked, not artificially liquidated.",
                "Single instrument; no portfolio optimization or tax-return computation.",
            ]}


def compare(path, *, exchange="NSE", bse_group=None, fixed_cost_inr="0"):
    bars = load_bars(path)
    runs = {name: simulate(bars, strategy=name, exchange=exchange, bse_group=bse_group,
                          fixed_cost_inr=fixed_cost_inr if name == "trend" else "0")
            for name in ("cash", "buy_hold", "trend")}
    return {"dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bars": len(bars), "fee_schedule_observed_on": str(OBSERVED_ON),
            "benchmark_cost_policy": "Cash and buy-hold assume no recurring research service; trend pays supplied fixed costs.",
            "comparison": runs, "profitability_proven": False, "live_orders": False}


def walk_forward_ranges(n, train, test, embargo):
    if min(train, test) <= 0 or embargo < 0:
        raise ValueError("Invalid fold sizes")
    cut = train
    while cut + embargo + test <= n:
        yield (0, cut, cut+embargo, cut+embargo+test)
        cut += test
