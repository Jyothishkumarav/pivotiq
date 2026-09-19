"""Populate stock_details from Yahoo Finance for every symbol in stock_symbols.

Runs a paced (rate-limit-friendly) loop through all 500 NSE symbols. Each call
uses `force_refresh=True` so it hits Yahoo and upserts the doc.

Usage from backend/ dir:

    python -m scripts.backfill_details             # skip symbols already in stock_details
    python -m scripts.backfill_details --all       # refresh every symbol
    python -m scripts.backfill_details --delay 5   # sleep 5s between symbols (default: 3)
    python -m scripts.backfill_details --limit 25  # only the first 25 symbols this run

The script is safely resumable: run it again and it picks up where it stopped.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pymongo import MongoClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import market_data  # noqa: E402


def _db():
    settings = get_settings()
    client = MongoClient(settings.mongo_uri)
    try:
        return client, client.get_default_database()
    except Exception:
        return client, client[settings.mongo_db_name]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between requests.")
    parser.add_argument("--limit", type=int, default=None, help="Max symbols this run.")
    parser.add_argument("--all", action="store_true", help="Refresh even symbols already in stock_details.")
    args = parser.parse_args()

    market_data.set_mode("real")
    client, db = _db()

    symbols = [d["symbol"] for d in db.stock_symbols.find({}, {"symbol": 1}).sort("symbol", 1)]
    if not args.all:
        existing = {d["symbol"] for d in db.stock_details.find({}, {"symbol": 1})}
        symbols = [s for s in symbols if s not in existing]

    if args.limit:
        symbols = symbols[: args.limit]

    total = len(symbols)
    if total == 0:
        print("Nothing to do — all symbols already have stock_details docs. Use --all to refresh.")
        client.close()
        return

    print(f"Backfilling {total} symbols (delay {args.delay}s between calls)…")
    successes = 0
    failures = 0
    for i, symbol in enumerate(symbols, start=1):
        try:
            details = market_data.get_details(symbol, force_refresh=True)
            if details and details.source == "yahoo":
                successes += 1
                marker = "OK"
            else:
                failures += 1
                marker = f"MISS ({details.source if details else 'None'})"
        except Exception as exc:  # noqa: BLE001
            failures += 1
            marker = f"ERROR ({exc.__class__.__name__})"
        print(f"[{i:>3}/{total}] {symbol:<12} → {marker}")
        if i < total:
            time.sleep(args.delay)

    print(f"\nDone. success={successes}  failure={failures}")
    client.close()


if __name__ == "__main__":
    main()
