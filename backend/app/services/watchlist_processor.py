"""Autonomous Watchlist Processor Daemon.

Runs as a server-side background task during market hours (09:15–15:30 IST).
Monitors active watchlists configured per user in user_settings, evaluating:
  1. Real-time intraday snapshots (ORB, VWAP, Breakout, Pullback stages)
  2. Multi-stage Telegram alerts:
     - Stage 3: Pullback Started
     - Stage 4: Support Candle Formed
     - Stage 5: Entry Triggered
     - SL Hit alerts
  3. Autonomous Dual Execution:
     - Universal Paper Trade placed on every trigger
     - Real Fyers MIS + SL-M order placed in parallel if autoTrade is enabled
  4. Pre-computed snapshot cache (`wl_snapshots:{id}`) for sub-10ms UI reads
  5. In-memory event-driven updates on stock add/remove/toggle with zero DB hammering.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dt_time, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo
from bson import ObjectId

from app.database import get_db
from app.schemas.stock import IntradaySnapshot
from app.services import intraday_analysis
from app.services.cache import get_cache_client
from app.services.fyers_client import FyersTokenExpired
from app.services.market_context import get_active_fyers_token
from app.services.notification_client import (
    notify_pullback_started,
    notify_stop_loss_hit,
    notify_support_candle_formed,
    notify_trade_setup_triggered,
)
from app.services.order_execution import trigger_autotrade_if_enabled

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_MARKET_OPEN_TIME = dt_time(9, 8)
_MARKET_CLOSE_TIME = dt_time(15, 35)
_CYCLE_INTERVAL_SECS = 4.0
_SNAPSHOT_CACHE_TTL = 30  # 30 seconds TTL for fast cache


def _is_market_hours() -> bool:
    """Checks whether the current time is within trading hours on a weekday."""
    now_ist = datetime.now(_IST)
    if now_ist.weekday() >= 5:  # Saturday or Sunday
        return False
    current_time = now_ist.time()
    return _MARKET_OPEN_TIME <= current_time <= _MARKET_CLOSE_TIME


class WatchlistProcessor:
    """Manages the background evaluation loop and in-memory watchlist states."""

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        # In-memory metadata map: watchlist_id -> dict
        # {
        #   "userId": str,
        #   "symbols": list[str],
        #   "strategy": str,
        #   "autoTrades": dict[str, bool],
        #   "name": str,
        # }
        self._watchlist_meta: dict[str, dict[str, Any]] = {}
        # In-memory map: user_id -> active_watchlist_id
        self._user_active_watchlist: dict[str, str] = {}
        # In-memory fast snapshot store: watchlist_id -> dict of symbol -> snapshot dict
        self._memory_snapshots: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="watchlist_processor_loop")
        logger.info("WatchlistProcessor daemon started successfully.")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("WatchlistProcessor daemon stopped.")

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "taskActive": self._task is not None and not self._task.done(),
            "isMarketHours": _is_market_hours(),
            "trackedWatchlists": len(self._watchlist_meta),
            "activeUsers": len(self._user_active_watchlist),
            "cachedWatchlists": list(self._memory_snapshots.keys()),
        }

    # -------------------------------------------------------------------------
    # Cache Accessors & Invalidation
    # -------------------------------------------------------------------------
    def get_cached_snapshots(self, watchlist_id: str) -> dict[str, Any] | None:
        """Fast read (< 5ms): checks in-memory first, then Redis."""
        wid = str(watchlist_id)
        if wid in self._memory_snapshots and self._memory_snapshots[wid]:
            return self._memory_snapshots[wid]

        try:
            cache = get_cache_client()
            cached = cache.get_json(f"wl_snapshots:{wid}")
            if cached and isinstance(cached, dict):
                self._memory_snapshots[wid] = cached
                return cached
        except Exception as exc:
            logger.debug("Redis cache read error for %s: %s", wid, exc)
        return None

    def set_cached_snapshots(self, watchlist_id: str, snapshots: dict[str, Any]) -> None:
        """Stores snapshots in memory and Redis with TTL."""
        wid = str(watchlist_id)
        self._memory_snapshots[wid] = snapshots
        try:
            cache = get_cache_client()
            cache.set_json(f"wl_snapshots:{wid}", snapshots, ttl_seconds=_SNAPSHOT_CACHE_TTL)
        except Exception as exc:
            logger.debug("Redis cache write error for %s: %s", wid, exc)

    def invalidate_cache(self, watchlist_id: str) -> None:
        wid = str(watchlist_id)
        self._memory_snapshots.pop(wid, None)
        try:
            cache = get_cache_client()
            cache.delete(f"wl_snapshots:{wid}")
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # In-Memory Event Mutation Handlers
    # -------------------------------------------------------------------------
    def notify_stock_added(self, watchlist_id: str, symbol: str, auto_trade: bool = False) -> None:
        wid = str(watchlist_id)
        sym = symbol.upper()
        meta = self._watchlist_meta.get(wid)
        if meta:
            if sym not in meta["symbols"]:
                meta["symbols"].append(sym)
            meta.setdefault("autoTrades", {})[sym] = auto_trade
        self.invalidate_cache(wid)
        logger.info("WatchlistProcessor: %s added to watchlist %s", sym, wid)

    def notify_stock_removed(self, watchlist_id: str, symbol: str) -> None:
        wid = str(watchlist_id)
        sym = symbol.upper()
        meta = self._watchlist_meta.get(wid)
        if meta:
            if sym in meta["symbols"]:
                meta["symbols"].remove(sym)
            meta.get("autoTrades", {}).pop(sym, None)
        if wid in self._memory_snapshots:
            self._memory_snapshots[wid].pop(sym, None)
        self.invalidate_cache(wid)
        logger.info("WatchlistProcessor: %s removed from watchlist %s", sym, wid)

    def notify_autotrade_toggled(self, watchlist_id: str, symbol: str, auto_trade: bool) -> None:
        wid = str(watchlist_id)
        sym = symbol.upper()
        meta = self._watchlist_meta.get(wid)
        if meta:
            meta.setdefault("autoTrades", {})[sym] = auto_trade
        logger.info("WatchlistProcessor: %s autoTrade set to %s in %s", sym, auto_trade, wid)

    def switch_active_watchlist(self, user_id: str | ObjectId, new_watchlist_id: str | None) -> None:
        uid = str(user_id)
        if new_watchlist_id:
            self._user_active_watchlist[uid] = str(new_watchlist_id)
            logger.info("WatchlistProcessor: User %s switched active watchlist to %s", uid, new_watchlist_id)
        else:
            self._user_active_watchlist.pop(uid, None)

    # -------------------------------------------------------------------------
    # Active Watchlist Sync from DB (Periodic)
    # -------------------------------------------------------------------------
    async def _sync_active_watchlists_from_db(self) -> None:
        """Discovers all users with trading configuration and their active watchlists."""
        try:
            db = get_db()
            settings_cursor = db.user_settings.find({"type": "trading_config"})
            async for doc in settings_cursor:
                uid = str(doc.get("userId"))
                cfg = doc.get("config", {})
                active_wid = cfg.get("activeWatchlistId")
                if active_wid and active_wid not in ("all", ""):
                    self._user_active_watchlist[uid] = str(active_wid)
                else:
                    # If not explicitly set, fallback to the user's first watchlist
                    user_ids = [uid]
                    if ObjectId.is_valid(uid):
                        user_ids.append(ObjectId(uid))
                    first_wl = await db.watchlists.find_one({"userId": {"$in": user_ids}})
                    if first_wl:
                        self._user_active_watchlist[uid] = str(first_wl["_id"])

            # Now load/update the metadata for all active watchlists
            active_wids = set(self._user_active_watchlist.values())
            for wid in active_wids:
                if not ObjectId.is_valid(wid):
                    continue
                wl_doc = await db.watchlists.find_one({"_id": ObjectId(wid)})
                if wl_doc:
                    raw_items = wl_doc.get("items", [])
                    self._watchlist_meta[wid] = {
                        "userId": str(wl_doc.get("userId")),
                        "symbols": [i["symbol"].upper() for i in raw_items if "symbol" in i],
                        "strategy": wl_doc.get("strategy", "orb_pullback_support"),
                        "autoTrades": {i["symbol"].upper(): bool(i.get("autoTrade", False)) for i in raw_items if "symbol" in i},
                        "name": wl_doc.get("name", "Watchlist"),
                    }
        except Exception as exc:
            logger.warning("WatchlistProcessor error syncing watchlists from DB: %s", exc)

    # -------------------------------------------------------------------------
    # Evaluation Cycle
    # -------------------------------------------------------------------------
    async def _evaluate_watchlist(self, wid: str) -> None:
        """Evaluates all symbols in an active watchlist, triggers alerts & orders."""
        meta = self._watchlist_meta.get(wid)
        if not meta or not meta["symbols"]:
            return

        user_id_str = meta["userId"]
        user_id_obj = ObjectId(user_id_str) if ObjectId.is_valid(user_id_str) else None
        if not user_id_obj:
            return

        token = await get_active_fyers_token(user_id_obj)
        if not token:
            logger.debug("No active Fyers token for user %s; skipping live processor evaluation", user_id_str)
            return

        strategy = meta.get("strategy", "orb_pullback_support")
        symbols = list(meta["symbols"])

        # Include benchmark indices for market context
        all_eval_symbols = list(symbols)
        for idx in ("NIFTY50", "BANKNIFTY"):
            if idx not in all_eval_symbols:
                all_eval_symbols.append(idx)

        sem = asyncio.Semaphore(2)

        async def _eval_one(sym: str) -> tuple[str, IntradaySnapshot | None]:
            async with sem:
                try:
                    await asyncio.sleep(0.08)
                    snap = await asyncio.to_thread(
                        intraday_analysis.compute_snapshot,
                        sym,
                        token,
                        strategy,
                        "close",
                        None,
                        False,
                    )
                    return sym.upper(), snap
                except FyersTokenExpired:
                    return sym.upper(), None
                except Exception as e:
                    logger.debug("Error computing snapshot for %s: %s", sym, e)
                    return sym.upper(), None

        results = await asyncio.gather(*[_eval_one(s) for s in all_eval_symbols])
        eval_dict: dict[str, Any] = {}
        index_snaps: dict[str, IntradaySnapshot] = {}

        for sym, snap in results:
            if snap is not None:
                if sym in ("NIFTY50", "BANKNIFTY", "NIFTY 50", "BANK NIFTY"):
                    index_snaps[sym] = snap
                eval_dict[sym] = snap.model_dump()

        # Update cache immediately so UI reads are sub-10ms
        if eval_dict:
            self.set_cached_snapshots(wid, eval_dict)

        # Process stage transitions, alerts & dual-order executions
        db = get_db()
        for sym, snap in results:
            if snap is None or sym in ("NIFTY50", "BANKNIFTY", "NIFTY 50", "BANK NIFTY"):
                continue

            setup = snap.tradeSetup
            if not setup:
                continue

            # Stage 3: Pullback Started
            if getattr(setup, "stageKey", None) == "pb_forming":
                asyncio.create_task(asyncio.to_thread(notify_pullback_started, snap, user_id_obj, index_snaps))

            # Stage 4: Support Candle Formed
            elif getattr(setup, "stageKey", None) == "support_formed":
                asyncio.create_task(asyncio.to_thread(notify_support_candle_formed, snap, user_id_obj, index_snaps))

            # Stage 5: Triggered Entry (Alert + Dual Execution)
            if setup.status == "triggered":
                asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snap, user_id_obj, index_snaps))
                asyncio.create_task(trigger_autotrade_if_enabled(snap, user_id_obj, db))

            # Stop Loss Hit
            elif setup.status == "sl_hit":
                asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snap, user_id_obj, index_snaps))

    # -------------------------------------------------------------------------
    # Main Daemon Loop
    # -------------------------------------------------------------------------
    async def _run_loop(self) -> None:
        """Main evaluation loop."""
        logger.info("WatchlistProcessor evaluation loop started.")
        sync_counter = 0

        while self._running:
            try:
                # 1. Market hours check
                if not _is_market_hours():
                    await asyncio.sleep(30.0)
                    continue

                # 2. Sync watchlists from DB every 10 cycles (~40 seconds)
                if sync_counter % 10 == 0:
                    await self._sync_active_watchlists_from_db()
                sync_counter += 1

                # 3. Evaluate each active watchlist in parallel
                active_wids = list(set(self._user_active_watchlist.values()))
                if active_wids:
                    await asyncio.gather(*[self._evaluate_watchlist(wid) for wid in active_wids], return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Unexpected error in WatchlistProcessor loop: %s", exc)

            await asyncio.sleep(_CYCLE_INTERVAL_SECS)


# Global singleton instance
watchlist_processor = WatchlistProcessor()
