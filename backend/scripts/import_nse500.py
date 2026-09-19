"""Import NSE 500 symbols + latest OHLC snapshot into MongoDB.

Reads `backend/data/nifty500_snapshot.csv` (the NSE Nifty 500 market-watch export)
and upserts each symbol into two collections:

  - `stock_symbols`         master + latest daily snapshot (OHLC, LTP, 52w, %chg)
  - `stock_fundamentals`    stub records ready to be enriched later (PE, PB, EPS…)

Run from repo root or backend/:

    python -m scripts.import_nse500
    # or
    python scripts/import_nse500.py

Idempotent: re-runs update existing docs by symbol.
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import ensure_indexes, get_client, get_db  # noqa: E402

CSV_PATH = REPO_ROOT / "data" / "nifty500_snapshot.csv"

# Symbols to skip — CSV includes the index itself as the first row.
_SKIP_SYMBOLS = {"NIFTY 500"}

# Match a date like "07-Sep-2026" inside the filename to record it on each doc.
_DATE_RE = re.compile(r"(\d{2}-[A-Za-z]{3}-\d{4})")


def _parse_number(raw: str) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("₹", "")
    if cleaned in ("", "-", "NA", "N/A"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    v = _parse_number(raw)
    return int(v) if v is not None else None


def _as_of_date_from_filename(path: Path) -> str | None:
    m = _DATE_RE.search(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _rows_from_csv(path: Path) -> list[dict]:
    as_of = _as_of_date_from_filename(path)
    docs: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = (row.get("SYMBOL") or "").strip()
            if not symbol or symbol.upper() in _SKIP_SYMBOLS:
                continue
            docs.append(
                {
                    "symbol": symbol.upper(),
                    "snapshot": {
                        "open": _parse_number(row.get("OPEN", "")),
                        "high": _parse_number(row.get("HIGH", "")),
                        "low": _parse_number(row.get("LOW", "")),
                        "prevClose": _parse_number(row.get("PREV. CLOSE", "")),
                        "ltp": _parse_number(row.get("LTP", "")),
                        "change": _parse_number(row.get("CHANGE", "")),
                        "changePercent": _parse_number(row.get("% CHANGE", "")),
                        "volume": _parse_int(row.get("VOLUME (shares)", "")),
                        "valueCrores": _parse_number(row.get("VALUE (₹ Crores)", "")),
                        "week52High": _parse_number(row.get("52 WEEK HIGH", "")),
                        "week52Low": _parse_number(row.get("52 WEEK LOW", "")),
                        "change30d": _parse_number(row.get("30 D %CHNG", "")),
                        "change365d": _parse_number(row.get("365 D %CHNG", "")),
                        "asOfDate": as_of,
                    },
                }
            )
    return docs


async def import_snapshot() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Snapshot CSV not found: {CSV_PATH}")

    docs = _rows_from_csv(CSV_PATH)
    if not docs:
        print("No rows to import.")
        return

    await ensure_indexes()
    db = get_db()
    now = datetime.now(timezone.utc)

    # Symbol master + latest snapshot.
    symbol_ops = [
        {
            "filter": {"symbol": d["symbol"]},
            "update": {
                "$set": {
                    "exchange": "NSE",
                    "index": "NIFTY 500",
                    "snapshot": d["snapshot"],
                    "updatedAt": now,
                },
                "$setOnInsert": {"createdAt": now},
            },
        }
        for d in docs
    ]

    # Fundamentals stubs — one per symbol, enrichable later.
    fundamentals_ops = [
        {
            "filter": {"symbol": d["symbol"]},
            "update": {
                "$setOnInsert": {
                    "symbol": d["symbol"],
                    "createdAt": now,
                    "marketCap": None,
                    "peRatio": None,
                    "pbRatio": None,
                    "eps": None,
                    "dividendYield": None,
                }
            },
        }
        for d in docs
    ]

    # Execute in bulk, but Motor doesn't expose a raw bulkWrite ergonomically —
    # per-doc upserts are fine at 500 symbols.
    for op in symbol_ops:
        await db.stock_symbols.update_one(op["filter"], op["update"], upsert=True)

    for op in fundamentals_ops:
        await db.stock_fundamentals.update_one(op["filter"], op["update"], upsert=True)

    total_symbols = await db.stock_symbols.count_documents({})
    total_fundamentals = await db.stock_fundamentals.count_documents({})
    print(f"Imported/updated {len(docs)} symbols from {CSV_PATH.name}.")
    print(f"stock_symbols       total docs: {total_symbols}")
    print(f"stock_fundamentals  total docs: {total_fundamentals}")


async def main() -> None:
    try:
        await import_snapshot()
    finally:
        get_client().close()


if __name__ == "__main__":
    asyncio.run(main())
