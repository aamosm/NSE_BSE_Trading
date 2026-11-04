from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import webbrowser
from datetime import datetime, timedelta, time as clock
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .backtest import compare, load_bars, simulate
from .audit import audit_dataset
from .common import IST, atomic_json, money, now, timestamp
from .dashboard import serve
from .kite import AuthenticationRequired, KiteError, KiteReadOnly, PermissionDenied
from .news import fetch_feed, ingest_feed
from .store import Store
from .experiments import Experiment

BAR_FIELDS = ["start", "end", "available_at", "open", "high", "low", "close", "volume"]


def state_write(root, **updates):
    path = root/"status.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    if "collection" in updates:
        updates["collection"] = {**state.get("collection", {}), **updates["collection"]}
    state.update(updates)
    state["live_orders"] = False
    atomic_json(path, state)


APP_FILE = "kite_app.json"  # API key and redirect port only; never the API secret
REQUEST_TOKEN = re.compile(r"[A-Za-z0-9]{6,64}")


ENV_FILE = ".env"  # private: KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID. Never a password or OTP seed.
FORBIDDEN_ENV = ("PASSWORD", "PASSWD", "PIN", "TOTP", "OTP")


def load_app(root):
    path = root/APP_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_env(root):
    """Read KEY=VALUE lines from the private env file. Login passwords/OTP seeds are refused, not used."""
    path = root/ENV_FILE
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if any(word in key for word in FORBIDDEN_ENV):
            raise ValueError(f"{path.name} contains {key}; broker passwords/OTP seeds must not be stored. "
                             "Remove it: Kite login is done by you in the browser")
        env[key] = value.strip().strip('"').strip("'")
    return env


class CallbackCatcher:
    """One-shot loopback listener for Kite's login redirect (the documented redirect flow, not a bypass).

    It binds 127.0.0.1 only, never logs request lines (they carry the request token) and stops after
    the first redirect with a well-formed request_token and status=success.
    """

    def __init__(self, port):
        result = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                q = parse_qs(urlsplit(self.path).query)
                token = q.get("request_token", [""])[0]
                ok = bool(REQUEST_TOKEN.fullmatch(token)) and q.get("status", ["success"])[0] == "success"
                body = (b"Kite login received. You can close this tab and return to the terminal." if ok
                        else b"Waiting for the Kite login redirect.")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if ok:
                    result["token"] = token

            def log_message(self, *args):
                pass

        self._result = result
        self.server = HTTPServer(("127.0.0.1", port), Handler)
        self.server.timeout = 0.5
        self.port = self.server.server_address[1]

    def wait(self, timeout=300.0):
        deadline = time.monotonic() + timeout
        while "token" not in self._result and time.monotonic() < deadline:
            self.server.handle_request()
        return self._result.get("token")

    def close(self):
        self.server.server_close()


def auth(root, no_browser=False, port=None, timeout=300.0):
    app, env = load_app(root), load_env(root)
    api_key = env.get("KITE_API_KEY") or app.get("api_key") or getpass.getpass("Kite API key (hidden): ").strip()
    secret = env.get("KITE_API_SECRET") or getpass.getpass("Kite API secret (hidden; not saved): ").strip()
    login_url = "https://kite.zerodha.com/connect/login?" + urlencode({"v": 3, "api_key": api_key})
    catcher = None
    if not no_browser:
        try:
            catcher = CallbackCatcher(int(port or app.get("redirect_port", 8766)))
        except OSError:
            print("Could not listen on the redirect port; falling back to pasting the redirected URL.")
    print("Complete Kite login yourself in the browser. No password or OTP is read by this program.")
    print("If the browser does not open, visit: " + login_url)
    token = ""
    try:
        if not no_browser:
            webbrowser.open(login_url)
        if catcher:
            print(f"Waiting up to {int(timeout)} s for the redirect to 127.0.0.1:{catcher.port} ...")
            token = catcher.wait(timeout) or ""
    finally:
        if catcher:
            catcher.close()
    if not token:
        value = getpass.getpass("Request token / redirected URL (hidden): ").strip()
        token = parse_qs(urlsplit(value).query).get("request_token", [""])[0] if "://" in value else value
    if not REQUEST_TOKEN.fullmatch(token):
        raise ValueError("No well-formed request_token was received; run auth again")
    session = KiteReadOnly(api_key).exchange_token(token, secret)
    access_token = session.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise KiteError("Token response was missing the access token")
    expected = env.get("KITE_USER_ID")
    if expected and session.get("user_id") != expected:
        raise KiteError("The account that logged in is not KITE_USER_ID from the private env file; session not saved")
    # Provider can invalidate a session earlier; 401/403 also stops collection.
    tomorrow = now().date() + timedelta(days=1)
    expires = datetime.combine(tomorrow, clock(6), IST)
    atomic_json(root/"kite_session.json", {"api_key": api_key, "access_token": access_token, "expires_at": expires.isoformat()})
    print("Session saved privately. Live order access is absent from this application.")


def client(root):
    path = root/"kite_session.json"
    if not path.exists():
        raise AuthenticationRequired("Run the auth command first")
    s = json.loads(path.read_text())
    if timestamp(s["expires_at"]) <= now():
        raise AuthenticationRequired("Daily Kite session expired. Run auth again.")
    return KiteReadOnly(s["api_key"], s["access_token"])


def collect_once(root, symbols, instruments=False):
    """Read account snapshots, then optional quotes/instrument dumps.

    An expired session stops everything. An endpoint the Kite plan does not include is recorded as
    unavailable and the remaining reads continue; nothing is retried automatically.
    """
    kite = client(root)
    db = Store(root/"evidence.sqlite3")
    counts, unavailable = {}, {}
    try:
        for kind, path in [("holdings", "/portfolio/holdings"), ("positions", "/portfolio/positions"),
                           ("trades", "/trades"), ("funds", "/user/margins/equity")]:
            try:
                payload = kite.get(path)
            except PermissionDenied:
                unavailable[kind] = "PERMISSION_DENIED"
                continue
            db.append(kind, "kite:" + path, "BROKER_ACCOUNT", payload)
            counts[kind] = len(payload) if isinstance(payload, list) else "snapshot"
        if symbols:
            try:
                payload = kite.quotes(symbols)
                db.append("quotes", "kite:/quote", "WATCHLIST", payload)
                counts["quotes"] = len(payload)
            except PermissionDenied:
                unavailable["quotes"] = "PERMISSION_DENIED (paid Kite Connect data plan required)"
        if instruments:
            for exchange in ("NSE", "BSE"):
                try:
                    raw = kite.get("/instruments/" + exchange)
                except PermissionDenied:
                    unavailable["instruments_" + exchange] = "PERMISSION_DENIED"
                    continue
                db.append("instrument_master", "kite:/instruments/" + exchange, exchange, {"csv": raw})
                # Instrument dump has no universal ISIN mapping; do not infer identity from token.
                atomic_json(root/("instruments_" + exchange + ".json"),
                            {"received_at": now(), "rows": list(csv.DictReader(io.StringIO(raw)))})
                counts["instruments_" + exchange] = "snapshot"
        status = "COLLECTED" if not unavailable else "COLLECTED_PARTIAL"
        state_write(root, collection={"status": status, "last_success_at": now(), "counts": counts,
                                      "unavailable": unavailable},
                    message="Broker snapshots were saved. No order or forecast was produced.")
    finally:
        db.close()
    print("Read-only collection complete." + (f" Not available on this plan: {', '.join(unavailable)}."
                                               if unavailable else ""))


def _num(x):
    try:
        return Decimal(str(x)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def summary_text(root):
    """Plain-text view of the latest collected snapshots (terminal only; never written to status.json)."""
    db = Store(root/"evidence.sqlite3")
    try:
        latest = {}
        for kind in ("holdings", "positions", "trades", "funds"):
            rows = db.as_of(kind, "BROKER_ACCOUNT", now())
            latest[kind] = rows[-1] if rows else None
    finally:
        db.close()
    if not any(latest.values()):
        return "No broker snapshot collected yet. Run auth, then collect."
    out = ["Read-only Kite snapshot (this application cannot place or change orders)."]
    h = latest["holdings"]
    if h is not None:
        rows = h["payload"] if isinstance(h["payload"], list) else []
        out.append(f"\nHoldings at {h['available_at']}: {len(rows)} stocks")
        invested = current = Decimal("0")
        for r in sorted(rows, key=lambda r: str(r.get("tradingsymbol", ""))):
            qty = int(r.get("quantity") or 0) + int(r.get("t1_quantity") or 0)
            avg, ltp = _num(r.get("average_price")), _num(r.get("last_price"))
            invested += avg * qty
            current += ltp * qty
            out.append(f"  {str(r.get('tradingsymbol', '?')):<14} {str(r.get('exchange', '')):<4} qty {qty:>6}  "
                       f"avg {avg:>10}  last {ltp:>10}  value {ltp * qty:>12}  P&L {ltp * qty - avg * qty:>11}")
        if rows:
            out.append(f"  Total invested {invested}  current {current}  unrealised P&L {current - invested}"
                       " (before selling costs)")
    f = latest["funds"]
    if f is not None and isinstance(f["payload"], dict):
        av = f["payload"].get("available") or {}
        ut = f["payload"].get("utilised") or {}
        out.append(f"\nEquity funds at {f['available_at']}: net {_num(f['payload'].get('net'))}, "
                   f"cash {_num(av.get('cash'))}, opening balance {_num(av.get('opening_balance'))}, "
                   f"live balance {_num(av.get('live_balance'))}, used {_num(ut.get('debits'))}")
    p = latest["positions"]
    if p is not None and isinstance(p["payload"], dict):
        net = [r for r in (p["payload"].get("net") or []) if isinstance(r, dict)]
        out.append(f"\nPositions at {p['available_at']}: {len(net)} (net view)")
        total = Decimal("0")
        for r in sorted(net, key=lambda r: (str(r.get("tradingsymbol", "")), str(r.get("product", "")))):
            pnl = _num(r.get("pnl"))
            total += pnl
            out.append(f"  {str(r.get('tradingsymbol', '?')):<14} {str(r.get('product', '')):<4} "
                       f"qty {int(r.get('quantity') or 0):>6}  bought {int(r.get('buy_quantity') or 0):>6}  "
                       f"sold {int(r.get('sell_quantity') or 0):>6}  avg {_num(r.get('average_price')):>10}  "
                       f"last {_num(r.get('last_price')):>10}  P&L {pnl:>10}")
        if net:
            out.append(f"  Total position P&L {total} (broker-reported, before charges)")
    t = latest["trades"]
    if t is not None:
        trades = [r for r in t["payload"] if isinstance(r, dict)] if isinstance(t["payload"], list) else []
        out.append(f"\nToday's executed trades: {len(trades)}")
        groups = {}
        for r in trades:
            k = (str(r.get("tradingsymbol", "?")), str(r.get("transaction_type", "?")), str(r.get("product", "")))
            qty = int(r.get("quantity") or 0)
            g = groups.setdefault(k, [0, 0, Decimal("0")])
            g[0] += 1
            g[1] += qty
            g[2] += _num(r.get("average_price")) * qty
        for (sym, side, prod), (n, qty, value) in sorted(groups.items()):
            out.append(f"  {sym:<14} {side:<4} {prod:<4} fills {n:>3}  qty {qty:>6}  value {value:>12}")
    return "\n".join(out)


def historical(root, token, interval, start, end, output, exchange, symbol, isin):
    start, end = timestamp(start), timestamp(end)
    if start >= end or end > now():
        raise ValueError("Choose an increasing historical interval ending no later than now")
    if interval not in {"day", "minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute"}:
        raise ValueError("Unsupported candle interval")
    if output.exists():
        raise ValueError("Output exists; choose a new dataset version")
    if exchange not in {"NSE", "BSE"} or not re.fullmatch(r"INE[A-Z0-9]{9}", isin):
        raise ValueError("Provide an NSE/BSE equity and a valid stock ISIN format")
    # Explicit provenance; download is not a survivorship-free historical universe.
    kite = client(root)
    master = list(csv.DictReader(io.StringIO(kite.get("/instruments/" + exchange))))
    match = [r for r in master if r["instrument_token"] == str(token)
             and r["tradingsymbol"] == symbol and r["exchange"] == exchange and r["instrument_type"] == "EQ"]
    if len(match) != 1:
        raise ValueError("Token/symbol/exchange is not a unique current equity instrument")
    max_chunk = timedelta(days=30 if interval == "day" else 5)
    if (end-start) / max_chunk > 100:
        raise ValueError("Request budget exceeded; split this history job into smaller ranges")
    db, candles, cursor = Store(root/"evidence.sqlite3"), {}, start
    try:
        while cursor < end:
            stop = min(end, cursor+max_chunk)
            payload = kite.history(token, interval, cursor.strftime("%Y-%m-%d %H:%M:%S"), stop.strftime("%Y-%m-%d %H:%M:%S"))
            db.append("history_download", "kite:history", f"{exchange}:{symbol}",
                      {"token": token, "interval": interval, "from": cursor, "to": stop, "data": payload})
            for row in payload["candles"]:
                stamp = timestamp(row[0])
                if start <= stamp <= end:
                    if stamp in candles and candles[stamp] != row:
                        raise ValueError("Conflicting historical candle revision; inspect raw evidence")
                    candles[stamp] = row
            cursor = stop
    finally:
        db.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Output exists; choose a new dataset version")
    with output.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BAR_FIELDS)
        writer.writeheader()
        for stamp, row in sorted(candles.items()):
            bar_end = (datetime.combine(stamp.date(), clock(23, 59, 59), IST) if interval == "day"
                       else stamp + timedelta(minutes=1 if interval == "minute" else int(interval.replace("minute", ""))))
            if bar_end > end or bar_end > now():
                continue  # Never export an incomplete candle.
            writer.writerow(dict(zip(BAR_FIELDS, [stamp.isoformat(), bar_end.isoformat(), bar_end.isoformat(), *row[1:6]])))
    atomic_json(output.with_suffix(".metadata.json"), {
        "source": "Kite historical REST", "retrieved_at": now(), "exchange": exchange, "symbol": symbol,
        "isin": isin, "instrument_token": token, "interval": interval,
        "isin_verification": "User-supplied; independently reconcile with exchange security master",
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "availability_assumption": "OHLC available after bar end; not original-vintage archived observations",
        "corporate_actions_verified": False, "historical_universe_verified": False,
        "historical_security_status_verified": False, "historical_fee_schedule_verified": False,
        "purpose": "exploratory research only; requires data audit before strategy certification"})
    print("Historical dataset and limitations metadata saved.")


def import_trades(root, path):
    db = Store(root/"evidence.sqlite3")
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        clean = []
        for row in rows:
            if row["side"] not in {"BUY", "SELL"} or row["exchange"] not in {"NSE", "BSE"}:
                raise ValueError("Invalid cash-equity trade")
            if int(row["quantity"]) <= 0 or money(row["price"]) <= 0 or money(row["fees"]) < 0:
                raise ValueError("Invalid quantity/price/fees")
            timestamp(row["executed_at"])
            if not all(row[k] for k in ("broker", "trade_id", "isin")):
                raise ValueError("Trade identity is missing")
            clean.append(row)
        for row in clean:
            db.append("external_trade", "manual:" + row["broker"] + ":" + row["trade_id"],
                      row["isin"], row, published_at=row["executed_at"])
    finally:
        db.close()
    print("External trade observations imported; no broker order was sent.")


def demo(output):
    output.mkdir(parents=True, exist_ok=True)
    path, day = output/"synthetic_daily.csv", datetime(2025, 1, 1, tzinfo=IST)
    rows = []
    for i in range(260):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = 100 + i*.08 + 7*math.sin(i/11)
        close = price + math.sin(i/3)
        rows.append([day.isoformat(), day.replace(hour=23, minute=59, second=59).isoformat(),
                     day.replace(hour=23, minute=59, second=59).isoformat(),
                     f"{price:.2f}", f"{max(price,close)+1:.2f}", f"{min(price,close)-1:.2f}", f"{close:.2f}", 100000])
        day += timedelta(days=1)
    with path.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(BAR_FIELDS); w.writerows(rows)
    report = compare(path)
    report["data_origin"] = "SYNTHETIC: no real stock or market performance"
    atomic_json(output/"demo_report.json", report)
    return report


def parser():
    p = argparse.ArgumentParser(description="NSE/BSE cash research. No live order commands exist.")
    p.add_argument("--private-dir", type=Path, default=Path("data/private"))
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("auth"); a.add_argument("--no-browser", action="store_true"); a.add_argument("--port", type=int)
    a.add_argument("--wait", type=float, default=300.0, help="seconds to wait for the browser login redirect")
    sub.add_parser("summary")
    a = sub.add_parser("collect"); a.add_argument("--symbols", nargs="*", default=[]); a.add_argument("--instruments", action="store_true")
    a = sub.add_parser("watch"); a.add_argument("--symbols", nargs="*", default=[]); a.add_argument("--interval", type=int, default=300)
    a = sub.add_parser("history")
    for name in ("token", "interval", "start", "end", "exchange", "symbol", "isin", "output"):
        a.add_argument("--"+name, required=True, type=int if name=="token" else Path if name=="output" else str)
    a = sub.add_parser("news"); a.add_argument("--file", type=Path); a.add_argument("--url")
    a = sub.add_parser("import-trades"); a.add_argument("file", type=Path)
    a = sub.add_parser("backtest"); a.add_argument("file", type=Path); a.add_argument("--output", type=Path)
    a.add_argument("--exchange", choices=["NSE", "BSE"], default="NSE"); a.add_argument("--bse-group")
    a.add_argument("--fixed-cost", default="0"); a.add_argument("--strategy", choices=["compare", "intraday_reversal"], default="compare")
    a = sub.add_parser("demo"); a.add_argument("--output", type=Path, default=Path("data/runs/demo"))
    a = sub.add_parser("dashboard"); a.add_argument("--port", type=int, default=8765)
    a = sub.add_parser("backup"); a.add_argument("destination", type=Path)
    a = sub.add_parser("audit"); a.add_argument("file", type=Path); a.add_argument("--output", type=Path, default=Path("data/runs/audit.json"))
    return p


def main():
    if hasattr(os, "umask"):
        os.umask(0o077)
    args = parser().parse_args()
    root = args.private_dir
    root.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "auth":
            auth(root, args.no_browser, args.port, args.wait)
        elif args.command == "summary":
            print(summary_text(root))
        elif args.command == "collect":
            collect_once(root, args.symbols, args.instruments)
        elif args.command == "watch":
            if args.interval < 60:
                raise ValueError("The collector interval must be at least 60 seconds")
            while True:
                local = now()
                if local.weekday() < 5 and clock(8, 30) <= local.time() <= clock(16, 15):
                    try:
                        collect_once(root, args.symbols)
                    except (KiteError, OSError, ValueError, RuntimeError) as e:
                        state_write(root, collection={"status": type(e).__name__, "attempt_at": now()},
                                    message="Collection is paused or failed. Check authentication and connectivity.")
                        print(type(e).__name__, flush=True)
                # Holiday/special-session collection needs an explicit calendar; no trading depends on this schedule.
                time.sleep(args.interval)
        elif args.command == "history":
            historical(root, args.token, args.interval, args.start, args.end, args.output, args.exchange, args.symbol, args.isin)
        elif args.command == "news":
            if bool(args.file) == bool(args.url):
                raise ValueError("Choose exactly one --file or --url")
            raw = args.file.read_bytes() if args.file else fetch_feed(args.url)
            db = Store(root/"evidence.sqlite3")
            try:
                ids = ingest_feed(db, raw, args.url or "file:" + args.file.name)
                print(f"Recorded {len(ids)} feed items as unreviewed evidence.")
            finally:
                db.close()
        elif args.command == "import-trades":
            import_trades(root, args.file)
        elif args.command == "backtest":
            parameters = {"strategy": args.strategy, "exchange": args.exchange,
                          "bse_group": args.bse_group, "fixed_cost": args.fixed_cost}
            with Experiment(root, args.file, parameters) as trial:
                output = args.output or Path("data/runs")/trial.run_id/"report.json"
                if output.exists():
                    raise ValueError("Output exists; choose a new experiment output path")
                if args.strategy == "compare":
                    report = compare(args.file, exchange=args.exchange, bse_group=args.bse_group, fixed_cost_inr=args.fixed_cost)
                else:
                    run = simulate(load_bars(args.file), strategy=args.strategy, exchange=args.exchange,
                                   bse_group=args.bse_group, fixed_cost_inr=args.fixed_cost)
                    report = {"comparison": {args.strategy: run}, "profitability_proven": False,
                              "dataset_sha256": hashlib.sha256(args.file.read_bytes()).hexdigest()}
                report["run_id"] = trial.run_id
                atomic_json(output, report)
                trial.output = output
            state_write(root, report=report, message="An exploratory historical comparison completed. No orders were sent.")
            print(f"Research report saved: {output}. Read its limitations before interpreting returns.")
        elif args.command == "demo":
            state_write(root, report=demo(args.output), message="Synthetic demonstration only. Kite has not been connected by this demo.")
            print("Synthetic demo complete. Run dashboard to view it.")
        elif args.command == "dashboard":
            print(f"Local dashboard: http://127.0.0.1:{args.port}")
            serve(root/"status.json", args.port)
        elif args.command == "backup":
            db = Store(root/"evidence.sqlite3")
            try:
                db.backup(args.destination)
            finally:
                db.close()
            print("Consistent SQLite backup saved.")
        elif args.command == "audit":
            atomic_json(args.output, audit_dataset(args.file))
            print("Dataset audit saved; unresolved data flags remain blockers to strategy certification.")
    except (KiteError, OSError, ValueError, KeyError, RuntimeError) as e:
        # Messages are this application's own (KiteError never carries provider bodies or tokens).
        print(f"{type(e).__name__}: {e}. Operation stopped; see docs/KITE_AND_SERVER_SETUP.md.", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("Stopped.")
