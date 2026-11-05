import csv
import importlib.util
import json
import zipfile
from pathlib import Path

from marketlab import kite_backfill


def _csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_backfill_planner_uses_bhavcopy_universe_and_records_survivorship_exclusions(tmp_path):
    instruments = _csv(
        tmp_path / "instruments.csv",
        "instrument_token,tradingsymbol,exchange,instrument_type\n"
        "101,ALIVE,NSE,EQ\n"
        "102,ETF,NSE,EQ\n",
    )
    bhav = _csv(
        tmp_path / "bhav.csv",
        "SYMBOL,SERIES,ISIN,OPEN,HIGH,LOW,CLOSE\n"
        "ALIVE,EQ,INEALIVE0001,1,1,1,1\n"
        "DEAD,EQ,INEDEAD00001,1,1,1,1\n"
        "ETF,BE,INEETF000001,1,1,1,1\n",
    )
    out = kite_backfill.dry_run(instruments, [bhav])
    assert out["status"] == "DRY_RUN"
    assert out["historical_isins"] == 2
    assert out["planned_candles"] == 1
    assert out["bhavcopy_only_isins_excluded"] == 1
    assert out["requests"] == [{"isin": "INEALIVE0001", "symbol": "ALIVE", "instrument_token": 101}]
    assert out["authentication"] == "NOT_ATTEMPTED"
    assert out["stages"] == list(kite_backfill.STAGES)


def test_backfill_planner_accepts_zip_fixture_and_rejects_ambiguous_current_symbol(tmp_path):
    instruments = _csv(
        tmp_path / "instruments.csv",
        "instrument_token,tradingsymbol,exchange,instrument_type\n"
        "101,SAME,NSE,EQ\n"
        "102,SAME,NSE,EQ\n",
    )
    csv_path = _csv(tmp_path / "legacy.csv", "SYMBOL,SERIES,ISIN\nSAME,EQ,INE000000001\n")
    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(csv_path, "legacy.csv")
    out = kite_backfill.dry_run(instruments, [archive])
    assert out["planned_candles"] == 0
    assert out["ambiguous_current_symbols_excluded"] == 1
    assert out["authentication"] == "NOT_ATTEMPTED"


def test_daily_update_dry_run_is_idempotent(tmp_path):
    spec = importlib.util.spec_from_file_location("daily_update", Path(__file__).parents[1] / "scripts" / "daily_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.run(tmp_path / "private", tmp_path / "market", day=__import__("datetime").date(2026, 11, 5),
                       dry_run=True)
    second = module.run(tmp_path / "private", tmp_path / "market", day=__import__("datetime").date(2026, 11, 5),
                        dry_run=True)
    assert first == second
    assert first["status"] == "DRY_RUN"
    assert "daily_update DRY_RUN" in module.summary(first)
    # A dry run leaves no day artifact: one would make the evening's real run short-circuit on work never done.
    assert not (tmp_path / "private" / "runs" / "daily_update" / "2026-11-05.json").exists()


def test_daily_update_only_short_circuits_on_a_completed_run(tmp_path):
    spec = importlib.util.spec_from_file_location("daily_update", Path(__file__).parents[1] / "scripts" / "daily_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    day = __import__("datetime").date(2026, 11, 5)
    out = tmp_path / "private" / "runs" / "daily_update" / "2026-11-05.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"status": "DRY_RUN", "day": "2026-11-05"}), encoding="utf-8")
    assert module.run(tmp_path / "private", tmp_path / "market", day=day, dry_run=True)["status"] == "DRY_RUN"
    out.write_text(json.dumps({"status": "COMPLETE", "day": "2026-11-05", "ranking": {"counts": {}}}), encoding="utf-8")
    done = module.run(tmp_path / "private", tmp_path / "market", day=day)  # no network: the stored run is returned
    assert done["status"] == "COMPLETE"
