"""Offline planning for a Kite candle backfill.

The planner never authenticates or downloads data. Historical universe membership
comes from exchange bhavcopies; the current Kite instrument dump is used only
to find candle tokens for symbols that still exist today.
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from pathlib import Path

STAGES = ("legacy_bhavcopies", "holiday_circulars", "kite_candles", "index_history", "isin_changes")


def _read_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise ValueError(f"bhavcopy archive must contain one file: {path}")
            return zf.read(names[0])
    return raw


def historical_universe(paths: list[Path]) -> dict[str, set[str]]:
    """Return historical ISIN -> symbols from legacy or UDiFF-like CSV fixtures.

    The parser accepts both legacy ``SYMBOL/ISIN`` headers and UDiFF names after
    removing punctuation and case differences. Missing identity fields fail
    explicitly instead of silently turning into symbol-only history.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        text = _read_bytes(path).decode("utf-8-sig")
        rows = csv.DictReader(io.StringIO(text))
        if not rows.fieldnames:
            raise ValueError(f"bhavcopy has no header: {path}")
        fields = {f.upper().replace("_", "").replace(" ", ""): f for f in rows.fieldnames if f}
        isin_key = fields.get("ISIN")
        symbol_key = fields.get("SYMBOL") or fields.get("TCKRSYMB")
        series_key = fields.get("SERIES") or fields.get("SCTYSRS")
        if not isin_key or not symbol_key:
            raise ValueError(f"bhavcopy lacks ISIN and symbol columns: {path}")
        for row in rows:
            isin, symbol = (row.get(isin_key) or "").strip().upper(), (row.get(symbol_key) or "").strip().upper()
            if not isin or not symbol:
                continue
            if series_key and (row.get(series_key) or "").strip().upper() != "EQ":
                continue
            out[isin].add(symbol)
    return dict(out)


def current_equity_tokens(instrument_csv: Path) -> dict[str, list[dict]]:
    """Index the current Kite equity dump by exchange symbol."""
    rows = csv.DictReader(io.StringIO(instrument_csv.read_text(encoding="utf-8-sig")))
    required = {"instrument_token", "tradingsymbol", "exchange", "instrument_type"}
    if not rows.fieldnames or not required <= set(rows.fieldnames):
        raise ValueError("Kite instrument dump lacks required identity columns")
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("exchange") == "NSE" and row.get("instrument_type") == "EQ":
            symbol = (row.get("tradingsymbol") or "").strip().upper()
            if symbol and row.get("instrument_token"):
                out[symbol].append(row)
    return dict(out)


def plan(historical: dict[str, set[str]], current: dict[str, list[dict]]) -> dict:
    """Create a no-network backfill plan and quantify survivorship exclusions."""
    requests, excluded, ambiguous = [], [], []
    for isin in sorted(historical):
        symbols = sorted(historical[isin])
        matches = [(symbol, current.get(symbol, [])) for symbol in symbols]
        usable = [(symbol, rows[0]) for symbol, rows in matches if len(rows) == 1]
        has_ambiguous = any(len(rows) > 1 for _, rows in matches)
        if len(usable) != 1:
            reason = "AMBIGUOUS_CURRENT_SYMBOL" if has_ambiguous else "HISTORICAL_SYMBOL_NOT_IN_CURRENT_MASTER"
            (ambiguous if reason.startswith("AMBIGUOUS") else excluded).append(
                {"isin": isin, "symbols": symbols, "reason": reason}
            )
            continue
        symbol, row = usable[0]
        requests.append({"isin": isin, "symbol": symbol, "instrument_token": int(row["instrument_token"])})
    return {
        "status": "DRY_RUN",
        "stages": list(STAGES),
        "historical_isins": len(historical),
        "planned_candles": len(requests),
        "bhavcopy_only_isins_excluded": len(excluded),
        "ambiguous_current_symbols_excluded": len(ambiguous),
        "excluded": excluded,
        "ambiguous": ambiguous,
        "requests": requests,
        "authentication": "NOT_ATTEMPTED",
        "network": "NOT_ATTEMPTED",
        "guard": "Kite instruments are not a historical universe; bhavcopies determine membership.",
    }


def dry_run(instrument_csv: Path, bhavcopies: list[Path]) -> dict:
    """Build a fixture-backed plan without reading credentials or contacting Kite."""
    return plan(historical_universe(bhavcopies), current_equity_tokens(instrument_csv))
