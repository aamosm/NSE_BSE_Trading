"""Dated paper cash/position ledger and the simulated execution policy EXEC.v1 (smallest complete version).

Everything a replay needs to be causal and to account for money exactly once:

* An INTENT is frozen after the close of decision session D from decision-time information only: quantity q,
  the decision close C_D, the limit L = C_D (1 + max_entry_gap) and the cash blocked for it at L (exact buy charges
  included). The next session's open never changes the intent.
* Execution at the open of the entry session (D+1, or D+2 in the late-entry stress), spec 2.2 plus the declared
  gap rule: fill at O (1 + s_in) when the security trades and that price is <= L; REJECTED_GAP above L;
  FILL_DEFERRED when it does not trade (no bar, zero volume, or locked at the upper band all session), and
  ENTRY_FAILED after more than 3 deferrals; CANCELLED_DATA_GAP when the session itself is missing from the data.
  No cash moves and no position exists before the fill.
* Exits execute at the open after the exit decision at O (1 - s_out). When the security cannot be sold (no bar,
  zero volume, locked at the lower band, missing session) the exit is BLOCKED and retried every session; the
  position stays in the books, marked at the last known close.
* Charges are the exact rupee-rounded schedule (``rules.charges.day_charges``), DP on the sell day. Slippage lives
  only in fill prices. Sale proceeds are unsettled until the settlement lag passes (T+1 from 27 Jan 2023, T+2
  before) and cannot fund an order before then; they still count in NAV.
* Corporate actions: on an ex-date with an exchange-implied factor f the units held become units / f; the trade is
  flagged FACTOR_UNVERIFIED unless the action is listed, and ACTION_COVERAGE_UNKNOWN when a held day could not be
  checked.
* NAV after every close = settled cash (including blocked reservations) + unsettled proceeds + positions at close.
  At the end, open positions are valued at liquidation (exit slippage and exact sell charges deducted); a
  position whose exit is blocked carries outcome bounds [0, liquidation value].
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ..costs import charges
from ..rules.charges import ZERODHA_2026_11_04 as SCHEDULE, Fill, TradeKind, day_charges
from ..rules.types import Exchange, Side
from . import labels
from .sessions import settlement_lag_sessions

D0 = Decimal("0")
PAISA = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(PAISA, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    version: str = "EXEC.v1"
    max_entry_gap: float = 0.05  # limit buy at C_D (1 + gap); funds are blocked at the limit
    max_deferral_sessions: int = 3  # spec 2.2
    entry_delay_sessions: int = 1  # 1 = next session's open (spec); 2 = one session late (stress)
    slippage_multiplier: float = 1.0  # stress: x2
    charge_multiplier: float = 1.0  # stress: x2

    def slippage(self, median_value_20: float) -> float:
        return labels.slippage_for(median_value_20) * self.slippage_multiplier

    def to_json(self) -> dict:
        return asdict(self) | {"entry_rule": "LIMIT_AT_OPEN_NEXT_SESSION", "exit_rule": "OPEN_AFTER_EXIT_DECISION",
                               "settlement": "T+1 from 2023-01-27, else T+2 (sessions)",
                               "slippage_per_side": {"liquid": labels.SLIPPAGE_LIQUID, "other": labels.SLIPPAGE_OTHER}}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()[:12]


def buy_charges(value: Decimal, day: date, isin: str, mult: float = 1.0) -> Decimal:
    c = day_charges(SCHEDULE, [Fill(day, Exchange.NSE, isin, TradeKind.DELIVERY, Side.BUY, value, 1, "b")]).total
    return money(c * Decimal(str(mult)))


def sell_charges(value: Decimal, day: date, isin: str, mult: float = 1.0) -> tuple[Decimal, Decimal]:
    """(total including DP, DP) for one delivery sell of ``value`` on ``day``."""
    dc = day_charges(SCHEDULE, [Fill(day, Exchange.NSE, isin, TradeKind.DELIVERY, Side.SELL, value, 1, "s")])
    m = Decimal(str(mult))
    return money(dc.total * m), money(dc.dp * m)


def reservation(q: int, limit: float, mult: float = 1.0) -> Decimal:
    """Cash blocked for a limit buy of q shares: value at the limit plus exact buy charges at that value."""
    v = money(q * limit)
    c = sum(charges(v, side="BUY", style="delivery").values(), D0)
    return v + money(c * Decimal(str(mult)))


def buyable(bar) -> str | None:
    """None if a buyer can trade at this session's open, else the reason. A session that traded at one price above
    the exchange base price all day is treated as locked at the upper band (no seller): conservative."""
    if bar is None or not (bar.volume > 0) or not (bar.open > 0):
        return "NOT_TRADED"
    if bar.high == bar.low and bar.prev_close and bar.close > bar.prev_close:
        return "LOCKED_UPPER_BAND"
    return None


def sellable(bar) -> str | None:
    if bar is None or not (bar.volume > 0) or not (bar.open > 0):
        return "NOT_TRADED"
    if bar.high == bar.low and bar.prev_close and bar.close < bar.prev_close:
        return "LOCKED_LOWER_BAND"
    return None


@dataclass
class Intent:
    intent_id: str
    isin: str
    symbol: str
    decision_day: date
    q: int
    ref_close: float
    limit: float
    slip_in: float
    slip_out: float
    reserved: Decimal
    execute_from: int  # session index of the first fill attempt
    forecast: dict
    deferrals: int = 0


@dataclass
class Lot:
    isin: str
    symbol: str
    intent_id: str
    decision_day: date
    q: int
    units: float
    entry_index: int
    entry_day: date
    entry_open: float
    entry_price: float
    buy_value: Decimal
    buy_charges: Decimal
    slip_in: float
    slip_out: float
    forecast: dict
    review_index: int
    last_close: float
    last_close_day: date
    factor: float = 1.0
    action_flags: set = field(default_factory=set)  # FACTOR_LISTED, FACTOR_UNVERIFIED, ACTION_COVERAGE_UNKNOWN
    exit_pending: bool = False
    exit_reason: str | None = None
    exit_decided_index: int | None = None
    blocked_sessions: int = 0
    holds: list = field(default_factory=list)


class Ledger:
    def __init__(self, capital: float, execution: ExecutionPolicy):
        self.W = money(capital)
        self.ex = execution
        self.cash = self.W  # settled cash, including amounts blocked for pending intents
        self.receivables: list[dict] = []  # unsettled sale proceeds {"amount", "usable_from", "trade"}
        self.intents: dict[str, Intent] = {}
        self.lots: dict[str, Lot] = {}
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.nav: list[dict] = []
        self.counts: dict[str, int] = {}

    # ---- bookkeeping ---------------------------------------------------------------------------------
    def event(self, kind: str, day: date, **kw):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.events.append({"event": kind, "day": day.isoformat(), **kw})

    def reserved(self) -> Decimal:
        return sum((i.reserved for i in self.intents.values()), D0)

    def available_cash(self, reserve_rupees: float) -> float:
        """Settled cash that may fund a new order: minus blocked reservations and the policy reserve."""
        return float(self.cash - self.reserved()) - reserve_rupees

    def settle(self, k: int, day: date):
        keep = []
        for r in self.receivables:
            if r["usable_from"] <= k:
                self.cash += r["amount"]
                self.event("PROCEEDS_SETTLED", day, amount=str(r["amount"]), trade=r["trade"])
            else:
                keep.append(r)
        self.receivables = keep

    def add_intent(self, it: Intent) -> bool:
        """Block the intent's cash. False (and an INTENT_UNFUNDED event) when free settled cash cannot cover it,
        e.g. in the costs x2 stress, whose decisions are made with the base cost model."""
        if it.reserved > self.cash - self.reserved():
            self.event("INTENT_UNFUNDED", it.decision_day, intent_id=it.intent_id, isin=it.isin, needed=str(it.reserved))
            return False
        self.intents[it.intent_id] = it
        self.event("INTENT", it.decision_day, intent_id=it.intent_id, isin=it.isin, q=it.q, ref_close=it.ref_close,
                   limit=round(it.limit, 4), reserved=str(it.reserved), execute_from=it.execute_from, forecast=it.forecast)
        return True

    # ---- the open of session k -----------------------------------------------------------------------
    def apply_actions(self, k: int, day: date, factors: dict[str, float], unchecked: bool, listed=None):
        """Ex-date adjustments for lots held overnight into ``day`` (entered before it)."""
        for lot in self.lots.values():
            if lot.entry_index >= k:
                continue
            if unchecked:
                lot.action_flags.add("ACTION_COVERAGE_UNKNOWN")
            f = factors.get(lot.isin)
            if f is None or abs(f - 1) <= labels.UNEXPLAINED_FACTOR_TOLERANCE:
                continue
            lot.units = lot.units / f
            lot.factor *= f
            lot.last_close = lot.last_close * f  # the previous close restated on the new basis
            is_listed = bool(listed and listed(lot.isin, day))
            lot.action_flags.add("FACTOR_LISTED" if is_listed else "FACTOR_UNVERIFIED")
            self.event("ACTION_APPLIED", day, isin=lot.isin, factor=f, units=lot.units, listed=is_listed)

    def execute_exits(self, k: int, day: date, have_session: bool, bars: dict, index_open: float | None):
        for isin, lot in list(self.lots.items()):
            if not lot.exit_pending or lot.exit_decided_index is None or lot.exit_decided_index >= k:
                continue
            why = "DATA_GAP" if not have_session else sellable(bars.get(isin))
            if why:
                lot.blocked_sessions += 1
                self.event("EXIT_BLOCKED", day, isin=isin, reason=why, blocked_sessions=lot.blocked_sessions)
                continue
            bar = bars[isin]
            price = bar.open * (1 - lot.slip_out * self.ex.slippage_multiplier)
            value = money(lot.units * price)
            total, dp = sell_charges(value, day, isin, self.ex.charge_multiplier)
            proceeds = value - total
            lag = settlement_lag_sessions(day)
            tid = f"{lot.intent_id}>{day.isoformat()}"
            self.receivables.append({"amount": proceeds, "usable_from": k + lag, "trade": tid})
            gross = lot.units * bar.open - lot.q * lot.entry_open
            slip = lot.q * lot.entry_open * lot.slip_in * self.ex.slippage_multiplier + lot.units * bar.open * lot.slip_out * self.ex.slippage_multiplier
            abs_ret = (bar.open / lot.factor) / lot.entry_open - 1
            cost = lot.buy_value + lot.buy_charges
            trade = {"trade_id": tid, "isin": isin, "symbol": lot.symbol, "intent_id": lot.intent_id,
                     "decision_day": lot.decision_day.isoformat(), "entry_day": lot.entry_day.isoformat(),
                     "exit_day": day.isoformat(), "q": lot.q, "units_exit": round(lot.units, 6),
                     "entry_open": lot.entry_open, "entry_price": round(lot.entry_price, 4), "exit_open": bar.open,
                     "exit_price": round(price, 4), "factor": lot.factor, "gross_rupees_at_open": round(gross, 2),
                     "slippage_rupees": round(slip, 2), "buy_value": str(lot.buy_value), "sell_value": str(value),
                     "charges": {"buy": str(lot.buy_charges), "sell_excl_dp": str(total - dp), "dp": str(dp),
                                 "total": str(lot.buy_charges + total)},
                     "net_rupees": float(proceeds - cost), "net_return": float((proceeds - cost) / cost),
                     "abs_return_gross": abs_ret, "index_open_entry": lot.forecast.get("_index_open_entry"),
                     "index_open_exit": index_open, "exit_reason": lot.exit_reason, "blocked_sessions": lot.blocked_sessions,
                     "action_status": ",".join(sorted(lot.action_flags)) or "NONE", "holding_sessions": k - lot.entry_index,
                     "holds": lot.holds, "settles_usable_from_index": k + lag,
                     "forecast": {kk: v for kk, v in lot.forecast.items() if not kk.startswith("_")}}
            ie = lot.forecast.get("_index_open_entry")
            if ie and index_open:
                trade["index_return"] = index_open / ie - 1
                trade["active_return_log"] = math.log1p(abs_ret) - math.log(index_open / ie)
            self.trades.append(trade)
            self.event("EXIT_FILLED", day, isin=isin, trade_id=tid, price=round(price, 4), proceeds=str(proceeds))
            del self.lots[isin]

    def execute_entries(self, k: int, day: date, have_session: bool, bars: dict, h: int, index_open: float | None):
        for iid, it in list(self.intents.items()):
            if it.execute_from > k:
                continue
            if not have_session:
                self._release(iid, day, "CANCELLED_DATA_GAP")
                continue
            why = buyable(bars.get(it.isin))
            if why:
                it.deferrals += 1
                if it.deferrals > self.ex.max_deferral_sessions:
                    self._release(iid, day, "ENTRY_FAILED", reason=why, deferrals=it.deferrals)
                else:
                    self.event("FILL_DEFERRED", day, intent_id=iid, reason=why, deferrals=it.deferrals)
                continue
            bar = bars[it.isin]
            price = bar.open * (1 + it.slip_in * self.ex.slippage_multiplier)
            if price > it.limit:
                self._release(iid, day, "REJECTED_GAP", open=bar.open, limit=round(it.limit, 4))
                continue
            value = money(it.q * price)
            ch = buy_charges(value, day, it.isin, self.ex.charge_multiplier)
            if value + ch > it.reserved:  # cannot happen at or below the limit; kept as an invariant
                self._release(iid, day, "REJECTED_CASH", cost=str(value + ch))
                continue
            del self.intents[iid]
            self.cash -= value + ch
            fc = dict(it.forecast, _index_open_entry=index_open)
            self.lots[it.isin] = Lot(it.isin, it.symbol, iid, it.decision_day, it.q, float(it.q), k, day, bar.open, price,
                                     value, ch, it.slip_in, it.slip_out, fc, k + h - 1, bar.close, day)
            self.event("FILLED", day, intent_id=iid, isin=it.isin, q=it.q, open=bar.open, price=round(price, 4),
                       value=str(value), charges=str(ch))

    def _release(self, iid: str, day: date, kind: str, **kw):
        it = self.intents.pop(iid)
        self.event(kind, day, intent_id=iid, isin=it.isin, released=str(it.reserved), **kw)

    # ---- the close of session k ----------------------------------------------------------------------
    def mark(self, k: int, day: date, closes: dict[str, float], have_session: bool):
        stale = 0
        value = 0.0
        for isin, lot in self.lots.items():
            c = closes.get(isin) if have_session else None
            if c and c > 0:
                lot.last_close, lot.last_close_day = c, day
            else:
                stale += 1
            value += lot.units * lot.last_close
        unsettled = sum((r["amount"] for r in self.receivables), D0)
        nav = float(self.cash + unsettled) + value
        self.nav.append({"day": day.isoformat(), "cash_settled": float(self.cash), "blocked": float(self.reserved()),
                         "unsettled": float(unsettled), "positions": round(value, 2), "nav": round(nav, 2),
                         "n_positions": len(self.lots), "stale_marks": stale})

    # ---- end of the simulated period ---------------------------------------------------------------
    def close_out(self, day: date) -> dict:
        """Pending intents are cancelled (no fill). Open positions are valued at liquidation from their last close:
        exit slippage and exact sell charges with DP deducted; blocked exits carry bounds [0, liquidation]."""
        for iid in list(self.intents):
            self._release(iid, day, "CANCELLED_AT_PERIOD_END")
        opens, liq_total, lower_total = [], D0, D0
        for isin, lot in self.lots.items():
            px = lot.last_close * (1 - lot.slip_out * self.ex.slippage_multiplier)
            value = money(lot.units * px) if lot.units * px > 0 else D0
            total = sell_charges(value, day, isin, self.ex.charge_multiplier)[0] if value > 0 else D0
            liq = max(D0, value - total)
            blocked = lot.exit_pending and lot.blocked_sessions > 0
            cost = lot.buy_value + lot.buy_charges
            liq_total += liq
            lower_total += D0 if blocked else liq
            opens.append({"isin": isin, "symbol": lot.symbol, "intent_id": lot.intent_id, "entry_day": lot.entry_day.isoformat(),
                          "q": lot.q, "units": round(lot.units, 6), "last_close": lot.last_close,
                          "last_close_day": lot.last_close_day.isoformat(), "cost": str(cost), "liquidation_value": str(liq),
                          "unrealized_net": float(liq - cost), "status": "EXIT_BLOCKED" if blocked else "OPEN_AT_PERIOD_END",
                          "outcome_bounds": [0.0, float(liq)] if blocked else [float(liq), float(liq)],
                          "action_status": ",".join(sorted(lot.action_flags)) or "NONE",
                          "blocked_sessions": lot.blocked_sessions})
        unsettled = sum((r["amount"] for r in self.receivables), D0)
        nav_liq = self.cash + unsettled + liq_total
        return {"open_positions": opens, "cash_settled": float(self.cash), "unsettled": float(unsettled),
                "nav_liquidation": float(nav_liq), "nav_liquidation_lower_bound": float(self.cash + unsettled + lower_total),
                "net_rupees": float(nav_liq - self.W), "realized_net": round(sum(t["net_rupees"] for t in self.trades), 2),
                "unrealized_net": round(sum(o["unrealized_net"] for o in opens), 2)}
