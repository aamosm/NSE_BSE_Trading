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
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .backtest import compare, load_bars, simulate
from .audit import audit_dataset
from .common import IST, atomic_json, money, now, timestamp
from .dashboard import serve
from .kite import AuthenticationRequired, KiteError, KiteReadOnly
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


def auth(root, no_browser=False):
    api_key = getpass.getpass("Kite API key (hidden): ").strip()
    secret = getpass.getpass("Kite API secret (hidden; not saved): ").strip()
    if not no_browser:
        webbrowser.open("https://kite.zerodha.com/connect/login?" + urlencode({"v": 3, "api_key": api_key}))
    print("Complete Kite login yourself. Paste the request_token or complete redirected URL below.")
    print("No password or OTP is read by this program. See docs/KITE_AND_SERVER_SETUP.md.")
    value = getpass.getpass("Request token / redirected URL (hidden): ").strip()
    token = parse_qs(urlsplit(value).query).get("request_token", [""])[0] if "://" in value else value
    session = KiteReadOnly(api_key).exchange_token(token, secret)
    access_token = session.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise KiteError("Token response was missing the access token")
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
    kite = client(root)
    db = Store(root/"evidence.sqlite3")
    counts = {}
    try:
        for kind, path in [("holdings", "/portfolio/holdings"), ("positions", "/portfolio/positions"),
                           ("trades", "/trades"), ("funds", "/user/margins/equity")]:
            payload = kite.get(path)
            db.append(kind, "kite:" + path, "BROKER_ACCOUNT", payload)
            counts[kind] = len(payload) if isinstance(payload, list) else "snapshot"
        if symbols:
            payload = kite.quotes(symbols)
            db.append("quotes", "kite:/quote", "WATCHLIST", payload)
            counts["quotes"] = len(payload)
        if instruments:
            for exchange in ("NSE", "BSE"):
                raw = kite.get("/instruments/" + exchange)
                db.append("instrument_master", "kite:/instruments/" + exchange, exchange, {"csv": raw})
                # Instrument dump has no universal ISIN mapping; do not infer identity from token.
                atomic_json(root/("instruments_" + exchange + ".json"),
                            {"received_at": now(), "rows": list(csv.DictReader(io.StringIO(raw)))})
        state_write(root, collection={"status": "COLLECTED", "last_success_at": now(), "counts": counts},
                    message="Broker snapshots were saved. No order or forecast was produced.")
    finally:
        db.close()
    print("Read-only collection complete.")


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
    a = sub.add_parser("auth"); a.add_argument("--no-browser", action="store_true")
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
            auth(root, args.no_browser)
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
        # Avoid accidental provider bodies, tokens or account data in diagnostic output.
        print(f"{type(e).__name__}: operation stopped. Check inputs, local permissions and the setup guide.", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("Stopped.")
