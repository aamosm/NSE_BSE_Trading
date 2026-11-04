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
import uuid
import webbrowser
from datetime import date, datetime, timedelta, time as clock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import account, login, master, service, sources, webapp
from .backtest import compare, load_bars, simulate
from .audit import audit_dataset
from .common import IST, atomic_json, money, now, timestamp
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


ENV_FILE = login.ENV_FILE  # private: see login.ALLOWED_ENV. Never a password, PIN or OTP seed.
load_env = login.load_env


class CallbackCatcher:
    """One-shot listener for Kite's login redirect on the registered loopback URL (documented flow).

    Binds 127.0.0.1 only, never logs request lines (they carry the request token), drops idle
    connections after a few seconds and accepts only the exact registered path with a valid,
    unexpired, single-use state. Anything else gets a neutral reply and is ignored.
    """

    def __init__(self, port, expected_path="/", states=None):
        result = {}
        states = states or login.StateBook()

        class Handler(BaseHTTPRequestHandler):
            timeout = 5  # finite read deadline for each browser connection

            def do_GET(self):
                try:
                    token = login.check_redirect(self.path, expected_path, states)
                except login.LoginRejected as e:
                    token, label = None, str(e)
                ok = token is not None
                body = (b"Kite login received. You can close this tab and return to the terminal." if ok
                        else ("Waiting for the Kite login redirect (" + label + ").").encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if ok:
                    result["token"] = token

            def log_message(self, *args):
                pass

        self._result = result
        # One thread per connection: idle browser pre-connections cannot delay the real redirect.
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
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
    """Terminal login. The registered redirect must be this machine's loopback URL (KITE_REDIRECT_URL)."""
    env = load_env(root)
    for key in ("KITE_API_KEY", "KITE_API_SECRET", "KITE_USER_ID"):
        if not env.get(key):
            raise ValueError(f"{key} is missing from {root / ENV_FILE}; the account check needs all three")
    redirect = urlsplit(login.redirect_url(env))
    if redirect.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("KITE_REDIRECT_URL points at the server; log in from the phone app instead")
    states = login.StateBook()
    state = states.issue()
    url = login.login_url(env["KITE_API_KEY"], state)
    catcher = None
    if not no_browser:
        try:
            catcher = CallbackCatcher(int(port if port is not None else redirect.port or 80),
                                      redirect.path or "/", states)
        except OSError:
            print("Could not listen on the redirect port; falling back to pasting the redirected URL.")
    print("Complete Kite login yourself in the browser. No password or OTP is read by this program.")
    print("If the browser does not open, visit: " + url)
    token = ""
    try:
        if not no_browser:
            webbrowser.open(url)
        if catcher:
            print(f"Waiting up to {int(timeout)} s for the redirect to 127.0.0.1:{catcher.port} ...")
            token = catcher.wait(timeout) or ""
    finally:
        if catcher:
            catcher.close()
    if not token:
        value = getpass.getpass("Redirected URL from the browser address bar (hidden): ").strip()
        u = urlsplit(value)
        token = login.check_redirect((u.path or "/") + "?" + u.query, redirect.path or "/", states)
    saved = login.complete_login(root, env, token)
    print(f"Session saved privately; it expires {saved['expires_at']}. Live order access is absent "
          "from this application.")


def client(root):
    path = root/"kite_session.json"
    if not path.exists():
        raise AuthenticationRequired("Run the auth command first")
    s = json.loads(path.read_text())
    if timestamp(s["expires_at"]) <= now():
        raise AuthenticationRequired("Daily Kite session expired. Run auth again.")
    return KiteReadOnly(s["api_key"], s["access_token"])


def collect_once(root, symbols, instruments=False):
    """Read account snapshots, then optional quotes/instrument dumps, as one collection batch.

    An expired session stops everything and leaves the batch incomplete (it is then ignored by account
    views). An endpoint the Kite plan does not include is recorded as unavailable and the remaining
    reads continue; nothing is retried automatically.
    """
    kite = client(root)
    db = Store(root/"evidence.sqlite3")
    batch, started = uuid.uuid4().hex, now()
    counts, unavailable = {}, {}
    try:
        for kind, path in [("holdings", "/portfolio/holdings"), ("positions", "/portfolio/positions"),
                           ("trades", "/trades"), ("funds", "/user/margins/equity")]:
            try:
                payload = kite.get(path)
            except PermissionDenied:
                unavailable[kind] = "PERMISSION_DENIED"
                continue
            db.append(kind, "kite:" + path, account.SUBJECT, payload, batch_id=batch)
            counts[kind] = len(payload) if isinstance(payload, list) else "snapshot"
        if symbols:
            try:
                payload = kite.quotes(symbols)
                db.append("quotes", "kite:/quote", "WATCHLIST", payload, batch_id=batch)
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
                db.append("instrument_master", "kite:/instruments/" + exchange, exchange, {"csv": raw}, batch_id=batch)
                # Instrument dump has no universal ISIN mapping; do not infer identity from token.
                atomic_json(root/("instruments_" + exchange + ".json"),
                            {"received_at": now(), "rows": list(csv.DictReader(io.StringIO(raw)))})
                counts["instruments_" + exchange] = "snapshot"
        status = "COLLECTED" if not unavailable else "COLLECTED_PARTIAL"
        db.append("collection_batch", "marketlab", account.SUBJECT,
                  {"batch_id": batch, "started_at": started, "status": status, "kinds": sorted(counts),
                   "unavailable": unavailable}, batch_id=batch)
        state_write(root, collection={"status": status, "last_success_at": now(), "counts": counts,
                                      "unavailable": unavailable},
                    message="Broker snapshots were saved. No order or forecast was produced.")
    finally:
        db.close()
    print("Read-only collection complete." + (f" Not available on this plan: {', '.join(unavailable)}."
                                               if unavailable else ""))


def summary_text(root):
    """Plain-text view of the latest completed collection batch (terminal only)."""
    db = Store(root/"evidence.sqlite3")
    try:
        return account.summary_text(account.account_view(db))
    finally:
        db.close()


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
        "series_kind": "PROVIDER_ORIGINAL", "adjustment_basis": "PROVIDER_AS_OF_RETRIEVAL",
        "adjustment_note": "Kite adjusts history for bonus, split, rights, spin-off and extraordinary dividends "
                           "before the ex-date open; prices before an action are NOT actual traded prices. Keep this "
                           "vintage; never apply the same actions again (marketlab.corporate_actions).",
        "corporate_actions_verified": False, "historical_universe_verified": False,
        "historical_security_status_verified": False, "historical_fee_schedule_verified": False,
        "purpose": "exploratory research only; requires data audit before strategy certification"})
    print("Historical dataset and limitations metadata saved.")


def dataset_bse_group(path: Path) -> str:
    """BSE fee group recorded with the dataset from listing data; never a command-line override."""
    meta_path = path.with_suffix(".metadata.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    group, source = meta.get("bse_group"), meta.get("bse_group_source")
    if not group or not source:
        raise ValueError("BSE charges depend on the scrip group; the dataset metadata must record bse_group "
                         "and bse_group_source from the security master")
    return group


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
    a = sub.add_parser("run", help="supervised scheduler: collection, daily inputs, health (no orders)")
    a.add_argument("--symbols", nargs="*", default=[], help="watchlist, e.g. NSE:INFY")
    a.add_argument("--interval", type=int, default=60); a.add_argument("--once", action="store_true")
    a.add_argument("--backups", type=Path)
    a = sub.add_parser("pause", help="pause paper analysis (collection continues)")
    a = sub.add_parser("resume", help="resume paper analysis")
    a = sub.add_parser("history")
    for name in ("token", "interval", "start", "end", "exchange", "symbol", "isin", "output"):
        a.add_argument("--"+name, required=True, type=int if name=="token" else Path if name=="output" else str)
    a = sub.add_parser("news"); a.add_argument("--file", type=Path); a.add_argument("--url")
    a = sub.add_parser("import-trades"); a.add_argument("file", type=Path)
    a = sub.add_parser("backtest"); a.add_argument("file", type=Path); a.add_argument("--output", type=Path)
    a.add_argument("--exchange", choices=["NSE", "BSE"], default="NSE")
    a.add_argument("--fixed-cost", default="0"); a.add_argument("--strategy", choices=["compare", "intraday_reversal"], default="compare")
    a = sub.add_parser("demo"); a.add_argument("--output", type=Path, default=Path("data/runs/demo"))
    a = sub.add_parser("dashboard", help="private phone app and Kite login callback (loopback only)")
    a.add_argument("--port", type=int, default=8765)
    a = sub.add_parser("backup"); a.add_argument("destination", type=Path)
    a = sub.add_parser("audit"); a.add_argument("file", type=Path); a.add_argument("--output", type=Path, default=Path("data/runs/audit.json"))
    a = sub.add_parser("fetch-public", help="download official NSE/BSE daily files for one trading date")
    a.add_argument("--date", type=date.fromisoformat, required=True); a.add_argument("--sources", nargs="*")
    a = sub.add_parser("verify-calendar", help="compare the engine's NSE calendar with NSE's holiday APIs")
    a.add_argument("--year", type=int, default=2026)
    a = sub.add_parser("build-master", help="security master usable for one session")
    a.add_argument("--date", type=date.fromisoformat, required=True)
    a = sub.add_parser("snapshot", help="rules-engine input for one NSE symbol and session, with provenance")
    a.add_argument("--date", type=date.fromisoformat, required=True); a.add_argument("--symbol", required=True)
    a = sub.add_parser("research-smoke", help="minimal real research-provider call (budgeted; never prints the key)")
    a.add_argument("--tools", action="store_true", help="also verify web_search + JSON schema + domain filter")
    a.add_argument("--search", action="store_true", help="one Search API request restricted to nseindia.com")
    sub.add_parser("research-usage", help="research spend this IST day and month against the caps")
    a = sub.add_parser("research-submit", help="queue one research job for an NSE symbol")
    a.add_argument("--kind", required=True, choices=sorted(__import__("marketlab.researcher.jobs", fromlist=["KINDS"]).KINDS))
    a.add_argument("--symbol", required=True); a.add_argument("--days", type=int, default=2)
    a.add_argument("--ir-domain", nargs="*", default=[]); a.add_argument("--alias", nargs="*", default=[])
    a = sub.add_parser("research-run", help="process research jobs (separate process from the scheduler)")
    a.add_argument("--loop", action="store_true"); a.add_argument("--interval", type=int, default=30)
    p.add_argument("--market-dir", type=Path, default=Path("data/market"))
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
        elif args.command == "run":
            if args.interval < 30:
                raise ValueError("The scheduler interval must be at least 30 seconds")
            ctx = service.Context(root, args.market_dir, args.symbols, backups=args.backups)
            service.run_forever(ctx, args.interval, iterations=1 if args.once else None)
            print("Service tick complete." if args.once else "Service stopped.")
        elif args.command in ("pause", "resume"):
            service.set_paused(root, args.command == "pause")
            print(f"Paper analysis {'paused' if args.command == 'pause' else 'resumed'}; collection is unaffected.")
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
            bse_group = dataset_bse_group(args.file) if args.exchange == "BSE" else None
            parameters = {"strategy": args.strategy, "exchange": args.exchange,
                          "bse_group": bse_group, "fixed_cost": args.fixed_cost}
            with Experiment(root, args.file, parameters) as trial:
                output = args.output or Path("data/runs")/trial.run_id/"report.json"
                if output.exists():
                    raise ValueError("Output exists; choose a new experiment output path")
                if args.strategy == "compare":
                    report = compare(args.file, exchange=args.exchange, bse_group=bse_group, fixed_cost_inr=args.fixed_cost)
                else:
                    run = simulate(load_bars(args.file), strategy=args.strategy, exchange=args.exchange,
                                   bse_group=bse_group, fixed_cost_inr=args.fixed_cost)
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
            print(f"Private app: http://127.0.0.1:{args.port} (on the server, reach it through Tailscale Serve)")
            webapp.serve(root, args.market_dir, args.port)
        elif args.command == "backup":
            db = Store(root/"evidence.sqlite3")
            try:
                db.backup(args.destination)
            finally:
                db.close()
            print("Consistent SQLite backup saved.")
        elif args.command == "fetch-public":
            for r in sources.collect(args.market_dir, args.date, args.sources):
                print(f"{r['source']:<28} {r.get('key', ''):<11} {r['result']}")
        elif args.command in ("research-smoke", "research-usage", "research-submit", "research-run"):
            from .researcher import commands as rc
            if args.command == "research-smoke":
                out = rc.search_smoke(root, args.market_dir) if args.search else rc.smoke(root, args.market_dir, args.tools)
            elif args.command == "research-usage":
                out = rc.usage(root, args.market_dir)
            elif args.command == "research-submit":
                out = rc.submit(root, args.market_dir, args.kind, args.symbol, args.days, args.ir_domain, args.alias)
            else:
                out = rc.run(root, args.market_dir, args.loop, args.interval)
            print(json.dumps(out, indent=1, default=str))
        elif args.command == "verify-calendar":
            print(json.dumps(sources.verify_nse_calendar(args.market_dir, args.year), indent=1))
        elif args.command == "build-master":
            print(json.dumps(master.build_master(args.market_dir, args.date), indent=1, default=str))
        elif args.command == "snapshot":
            snap, prov = master.build_nse_snapshot(args.market_dir, args.symbol, args.date)
            print(json.dumps({"snapshot": master.snapshot_json(snap), "provenance": prov}, indent=1, default=str))
        elif args.command == "audit":
            atomic_json(args.output, audit_dataset(args.file))
            print("Dataset audit saved; unresolved data flags remain blockers to strategy certification.")
    except (KiteError, OSError, ValueError, KeyError, RuntimeError) as e:
        # Messages are this application's own (KiteError never carries provider bodies or tokens).
        print(f"{type(e).__name__}: {e}. Operation stopped; see docs/KITE_AND_SERVER_SETUP.md.", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("Stopped.")
