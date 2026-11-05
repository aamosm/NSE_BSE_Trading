"""Acquire public data, rebuild the panel, rank, and record forward evidence.

This is research-only. It is intentionally a thin orchestration script: each
underlying operation remains independently testable and no broker endpoint is
called.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from marketlab import service, sources
from marketlab.common import atomic_json, now
from marketlab.quant import panel as qpanel, ranking
from marketlab.quant.panel import Panel


def run(root: Path, market: Path, *, day: date | None = None, capital: float | None = None,
        dry_run: bool = False, bootstrap: int = 50) -> dict:
    day = day or now().date()
    out_path = root / "runs" / "daily_update" / f"{day.isoformat()}.json"
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    if dry_run:
        result = {"status": "DRY_RUN", "day": day.isoformat(), "acquire": "NOT_ATTEMPTED",
                  "panel": "NOT_ATTEMPTED", "ranking": "NOT_ATTEMPTED", "forward": "NOT_ATTEMPTED"}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(out_path, result)
        return result

    source_ids = [s.id for s in sources.REGISTER if s.dated and s.status == "WORKS"]
    acquired = sources.collect(market, day, source_ids)
    failed = [r["source"] for r in acquired if r["result"] in ("FAILED", "SCHEMA_CHANGED")]
    if failed:
        raise RuntimeError("PUBLIC_ACQUISITION_FAILED:" + ",".join(failed))
    panel_result = qpanel.build(market)
    calendar = sources.load_calendar_for(market)[0]
    ranked = service.build_ranking(root, market, calendar, capital=capital, bootstrap=bootstrap, origin="daily_update")
    pn = Panel(market / "panel.sqlite3")
    try:
        forward = ranking.forward_record(pn, calendar, root)
    finally:
        pn.close()
    result = {"status": "COMPLETE", "day": day.isoformat(), "acquire": acquired,
              "panel": panel_result, "ranking": ranked, "forward": forward}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(out_path, result)
    return result


def summary(result: dict) -> str:
    ranking_result = result.get("ranking")
    counts = ranking_result.get("counts", {}) if isinstance(ranking_result, dict) else {}
    return "\n".join([
        f"daily_update {result.get('status', 'UNKNOWN')} {result.get('day', 'unknown')}",
        f"acquire: {len(result.get('acquire', [])) if isinstance(result.get('acquire'), list) else result.get('acquire')}",
        f"panel: {result.get('panel', {}).get('sessions_total', result.get('panel')) if isinstance(result.get('panel'), dict) else result.get('panel')}",
        f"ranking: {counts.get('BUY_CANDIDATE', 0)} buy, {counts.get('QUALIFIES', 0)} qualifies",
        f"forward: {len(result.get('forward', {}).get('rankings', [])) if isinstance(result.get('forward'), dict) else result.get('forward')}",
    ])


def main() -> None:
    p = argparse.ArgumentParser(description="Research-only daily MarketLab update; no orders.")
    p.add_argument("--private-dir", type=Path, default=Path("data/private"))
    p.add_argument("--market-dir", type=Path, default=Path("data/market"))
    p.add_argument("--date", type=date.fromisoformat)
    p.add_argument("--capital", type=float)
    p.add_argument("--bootstrap", type=int, default=50)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(summary(run(args.private_dir, args.market_dir, day=args.date, capital=args.capital,
                       dry_run=args.dry_run, bootstrap=args.bootstrap)))


if __name__ == "__main__":
    main()
