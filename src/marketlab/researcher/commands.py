"""CLI entry points for the research service (separate process from the scheduler). No provider is configured
by default; a future adapter is selected by RESEARCH_PROVIDER in the private env file."""
from __future__ import annotations

import sqlite3
import time
from datetime import timedelta
from pathlib import Path

from .. import login
from ..common import now
from . import jobs
from .budget import Ledger, Policy
from .provider import NullProvider

OFFICIAL = {"EXCHANGE": ["nseindia.com", "bseindia.com"], "REGULATOR": ["sebi.gov.in"]}


def paths(market: Path) -> dict:
    base = market / "research"
    return {"base": base, "ledger": base / "ledger.sqlite3", "queue": base / "queue.sqlite3"}


def provider_and_env(root: Path):
    env = login.load_env(root)
    name = env.get("RESEARCH_PROVIDER", "").strip().lower()
    if name and name != "none":
        raise ValueError(f"No adapter is implemented for RESEARCH_PROVIDER={name}; see researcher/provider.py")
    return NullProvider(), [v for v in env.values() if v]


def usage(root: Path, market: Path) -> dict:
    ledger = Ledger(paths(market)["ledger"], Policy.load(root / "research_policy.json"))
    try:
        s = ledger.spent()
        pol = ledger.policy
        return {"month_usd": str(s["month"]), "monthly_cap_usd": str(pol.monthly_usd), "day_usd": str(s["day"]),
                "daily_cap_usd": str(pol.daily_usd), "open_reservations": s["open_reservations"], "jobs_today": s["day_count"],
                "provider": provider_and_env(root)[0].name}
    finally:
        ledger.close()


def entity_for(market: Path, symbol: str, aliases=()) -> dict:
    db = sqlite3.connect(market / "master.sqlite3")
    try:
        latest = db.execute("SELECT max(snapshot_date) FROM listings").fetchone()[0]
        row = db.execute("SELECT isin, name FROM listings WHERE snapshot_date=? AND exchange='NSE' AND symbol=?",
                         (latest, symbol)).fetchone()
        if not row:
            raise ValueError(f"{symbol} not in the security master for {latest}")
        bse = db.execute("SELECT exchange_code FROM listings WHERE snapshot_date=? AND exchange='BSE' AND isin=?",
                         (latest, row[0])).fetchone()
    finally:
        db.close()
    return {"isin": row[0], "nse_symbol": symbol, "bse_code": bse[0] if bse else None, "name": row[1], "aliases": list(aliases)}


def submit(root: Path, market: Path, kind: str, symbol: str, days: int, ir_domains=(), aliases=(), trigger=None,
           known_facts=()) -> dict:
    entity = entity_for(market, symbol, aliases)
    allowed = dict(OFFICIAL)
    if ir_domains:
        allowed["COMPANY_IR"] = list(ir_domains)
    end = now()
    start = end - timedelta(days=days)
    if kind == "upcoming_event_verification":
        end = end + timedelta(days=days)
        start = now() - timedelta(days=30)
    job = jobs.new_job(kind, entity, start, end, allowed, trigger=trigger, known_facts=tuple(known_facts))
    q = jobs.Queue(paths(market)["queue"])
    try:
        return {"job_id": job.job_id, "state": q.submit(job), "isin": entity["isin"]}
    finally:
        q.close()


def run(root: Path, market: Path, loop=False, interval=30) -> list:
    provider, private = provider_and_env(root)
    p = paths(market)
    outcomes = []
    while True:
        q, ledger, archive = jobs.Queue(p["queue"]), Ledger(p["ledger"], Policy.load(root / "research_policy.json")), \
            jobs.Archive(p["base"])
        try:
            out = jobs.run_one(q, provider, ledger, archive, private_values=private)
        finally:
            q.close(); ledger.close(); archive.close()
        outcomes.append(out)
        if not loop:
            return outcomes
        time.sleep(max(5, interval))
