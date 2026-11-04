"""Actual-account view built from one completed read-only collection batch.

Rules (review of 3513d33, finding 1):
* The current state is the newest *completed* batch received at or before the view time. Every kind
  comes from that batch only; a kind missing from it is UNAVAILABLE, never an older snapshot.
* Each section carries its own state: OK, STALE (not from today's date), UNAVAILABLE, MALFORMED or
  MISSING. Missing or unparseable numbers are ``None`` (unknown), never zero, and any total that would
  include an unknown is itself unknown.
* Kite's trade book is a current-day book. A trade snapshot is attributed to a session only when it
  was received on a trading day after that day's pre-open start; otherwise its day is unknown. A new
  day without trades therefore never shows yesterday's trades as today's.

This is the owner's real account. It is never mixed with simulated (paper) figures.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from .common import now, timestamp
from .rules.calendar import MarketCalendar
from .rules.types import Exchange, RuleUnknown

KINDS = ("holdings", "positions", "trades", "funds")
SUBJECT = "BROKER_ACCOUNT"
SESSION_OPEN = time(9, 0)  # earliest pre-open order entry on a regular day


def num(x) -> Decimal | None:
    """Decimal or None. Booleans, blanks, NaN and infinities are unknown, not zero."""
    if x is None or isinstance(x, bool) or (isinstance(x, str) and not x.strip()):
        return None
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def qty(x) -> int | None:
    d = num(x)
    return int(d) if d is not None and d == d.to_integral_value() else None


def total(values):
    values = list(values)
    if any(v is None for v in values):
        return None
    return sum(values, Decimal("0"))


def _money(d):
    return None if d is None else d.quantize(Decimal("0.01"))


def trade_session_date(received: datetime, calendar: MarketCalendar | None = None):
    """The session a current-day trade book belongs to, or None when that cannot be established."""
    cal = calendar or MarketCalendar()
    local = timestamp(received)
    try:
        trading = cal.is_trading_day(Exchange.NSE, local.date())
        opens = cal.session_open(Exchange.NSE, local.date()) if trading else None
    except RuleUnknown:
        return None
    if not trading or opens is None or local.time() < opens:
        return None
    return local.date()


def latest_batch(db, at=None):
    """The newest completed collection batch record received at or before ``at``."""
    rec = db.latest("collection_batch", SUBJECT, at)
    if rec is None or not isinstance(rec["payload"], dict) or not rec["payload"].get("batch_id"):
        return None
    return rec


def _holdings(payload):
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        return {"state": "MALFORMED"}
    rows = []
    for r in payload:
        q, t1 = qty(r.get("quantity")), qty(r.get("t1_quantity"))
        held = None if q is None or t1 is None else q + t1
        avg, last = num(r.get("average_price")), num(r.get("last_price"))
        invested = None if held is None or avg is None else avg * held
        value = None if held is None or last is None else last * held
        rows.append({"symbol": str(r.get("tradingsymbol") or "?"), "exchange": str(r.get("exchange") or ""),
                     "isin": r.get("isin"), "quantity": held, "average_price": avg, "last_price": last,
                     "invested": _money(invested), "value": _money(value),
                     "pnl": _money(None if invested is None or value is None else value - invested)})
    rows.sort(key=lambda r: r["symbol"])
    inv, val = total(r["invested"] for r in rows), total(r["value"] for r in rows)
    return {"state": "OK", "rows": rows, "count": len(rows),
            "totals": {"invested": inv, "value": val, "pnl": None if inv is None or val is None else val - inv}}


def _funds(payload):
    if not isinstance(payload, dict):
        return {"state": "MALFORMED"}
    av = payload.get("available") if isinstance(payload.get("available"), dict) else {}
    ut = payload.get("utilised") if isinstance(payload.get("utilised"), dict) else {}
    return {"state": "OK", "net": _money(num(payload.get("net"))), "cash": _money(num(av.get("cash"))),
            "opening_balance": _money(num(av.get("opening_balance"))),
            "live_balance": _money(num(av.get("live_balance"))), "used": _money(num(ut.get("debits")))}


def _positions(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("net"), list):
        return {"state": "MALFORMED"}
    rows = []
    for r in payload["net"]:
        if not isinstance(r, dict):
            return {"state": "MALFORMED"}
        rows.append({"symbol": str(r.get("tradingsymbol") or "?"), "product": str(r.get("product") or ""),
                     "quantity": qty(r.get("quantity")), "bought": qty(r.get("buy_quantity")),
                     "sold": qty(r.get("sell_quantity")), "average_price": num(r.get("average_price")),
                     "last_price": num(r.get("last_price")), "pnl": _money(num(r.get("pnl")))})
    rows.sort(key=lambda r: (r["symbol"], r["product"]))
    return {"state": "OK", "rows": rows, "count": len(rows), "totals": {"pnl": total(r["pnl"] for r in rows)}}


def _trades(payload):
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        return {"state": "MALFORMED"}
    groups = {}
    for r in payload:
        k = (str(r.get("tradingsymbol") or "?"), str(r.get("transaction_type") or "?"), str(r.get("product") or ""))
        q, p = qty(r.get("quantity")), num(r.get("average_price"))
        g = groups.setdefault(k, {"fills": 0, "quantity": 0, "value": Decimal("0")})
        g["fills"] += 1
        g["quantity"] = None if g["quantity"] is None or q is None else g["quantity"] + q
        g["value"] = None if g["value"] is None or q is None or p is None else g["value"] + p * q
    rows = [{"symbol": s, "side": side, "product": prod, **g, "value": _money(g["value"])}
            for (s, side, prod), g in sorted(groups.items())]
    return {"state": "OK", "rows": rows, "fills": len(payload)}


PARSERS = {"holdings": _holdings, "positions": _positions, "trades": _trades, "funds": _funds}


def account_view(db, at=None, calendar: MarketCalendar | None = None):
    at = timestamp(at) if at else now()
    batch = latest_batch(db, at)
    view = {"as_of": at.isoformat(), "kind": "ACTUAL_ACCOUNT", "batch": None, "sections": {}}
    if batch is None:
        for kind in KINDS:
            view["sections"][kind] = {"state": "MISSING"}
        return view
    meta = batch["payload"]
    view["batch"] = {"id": meta["batch_id"], "finished_at": batch["received_at"],
                     "status": meta.get("status"), "unavailable": sorted(meta.get("unavailable", {}))}
    for kind in KINDS:
        rec = db.latest(kind, SUBJECT, at, batch_id=meta["batch_id"])
        if rec is None:
            reason = "UNAVAILABLE" if kind in meta.get("unavailable", {}) else "MISSING"
            view["sections"][kind] = {"state": reason}
            continue
        section = PARSERS[kind](rec["payload"])
        received = timestamp(rec["received_at"])
        section.update(received_at=rec["received_at"], first_received_at=rec["first_received_at"])
        if section["state"] == "OK":
            if kind == "trades":
                day = trade_session_date(received, calendar)
                section["session_date"] = day.isoformat() if day else None
                if day != at.date():
                    section["state"] = "STALE" if day else "SESSION_UNKNOWN"
            elif received.date() != at.date():
                section["state"] = "STALE"
        view["sections"][kind] = section
    return view


def _when(iso):
    return timestamp(iso).strftime("%Y-%m-%d %H:%M IST")


def _fmt(x, width=0):
    s = "unknown" if x is None else str(x)
    return s.rjust(width) if width else s


def summary_text(view):
    """Terminal rendering of ``account_view``. Never written to status files or sent to a model."""
    if view["batch"] is None:
        return "No completed broker collection yet. Run auth, then collect."
    s = view["sections"]
    out = ["ACTUAL account, read-only Kite snapshot (this application cannot place or change orders).",
           f"Collection batch finished {_when(view['batch']['finished_at'])} ({view['batch']['status']})."]

    def head(name, label):
        sec = s[name]
        if sec["state"] in ("MISSING", "UNAVAILABLE", "MALFORMED"):
            out.append(f"\n{label}: {sec['state'].lower()} in the latest batch (treated as unknown, not zero)")
            return None
        tag = "" if sec["state"] == "OK" else f" [{sec['state']}: not from today]"
        return sec, tag

    h = head("holdings", "Holdings")
    if h:
        sec, tag = h
        out.append(f"\nHoldings at {_when(sec['received_at'])}{tag}: {sec['count']} stocks")
        for r in sec["rows"]:
            out.append(f"  {r['symbol']:<14} {r['exchange']:<4} qty {_fmt(r['quantity'], 6)}  "
                       f"avg {_fmt(r['average_price'], 10)}  last {_fmt(r['last_price'], 10)}  "
                       f"value {_fmt(r['value'], 12)}  P&L {_fmt(r['pnl'], 11)}")
        if sec["rows"]:
            t = sec["totals"]
            out.append(f"  Total invested {_fmt(t['invested'])}  current {_fmt(t['value'])}  "
                       f"unrealised P&L {_fmt(t['pnl'])} (before selling costs)")
    f = head("funds", "Equity funds")
    if f:
        sec, tag = f
        out.append(f"\nEquity funds at {_when(sec['received_at'])}{tag}: net {_fmt(sec['net'])}, cash {_fmt(sec['cash'])}, "
                   f"opening balance {_fmt(sec['opening_balance'])}, live balance {_fmt(sec['live_balance'])}, "
                   f"used {_fmt(sec['used'])}")
    p = head("positions", "Positions")
    if p:
        sec, tag = p
        out.append(f"\nPositions at {_when(sec['received_at'])}{tag}: {sec['count']} (net view)")
        for r in sec["rows"]:
            out.append(f"  {r['symbol']:<14} {r['product']:<4} qty {_fmt(r['quantity'], 6)}  "
                       f"bought {_fmt(r['bought'], 6)}  sold {_fmt(r['sold'], 6)}  avg {_fmt(r['average_price'], 10)}  "
                       f"last {_fmt(r['last_price'], 10)}  P&L {_fmt(r['pnl'], 10)}")
        if sec["rows"]:
            out.append(f"  Total position P&L {_fmt(sec['totals']['pnl'])} (broker-reported, before charges)")
    t = head("trades", "Trades")
    if t:
        sec, _ = t
        if sec["state"] == "OK":
            out.append(f"\nToday's executed trades ({sec['session_date']}): {sec['fills']} fills")
        elif sec["state"] == "STALE":
            out.append(f"\nNo trade snapshot for today yet. Latest trade book is for {sec['session_date']}: "
                       f"{sec['fills']} fills")
        else:
            out.append(f"\nTrade book received {_when(sec['received_at'])} outside a known session; its day is unknown "
                       f"({sec['fills']} fills)")
        for r in sec["rows"]:
            out.append(f"  {r['symbol']:<14} {r['side']:<4} {r['product']:<4} fills {r['fills']:>3}  "
                       f"qty {_fmt(r['quantity'], 6)}  value {_fmt(r['value'], 12)}")
    return "\n".join(out)
