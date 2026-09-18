"""Intraday analysis — Opening Range Breakout (ORB) + VWAP.

Uses Fyers' 5-minute historical candles to compute:

- **Opening range** (first 3 x 5-min candles = 9:15-9:30 IST): sets the intraday
  high/low used as dynamic support/resistance.
- **VWAP** (Volume-Weighted Average Price): cumulative from open. A common
  intraday level traders use for mean reversion / trend confirmation.
- **Trend**: up if current price broke ORB high, down if broke ORB low, flat
  if still inside the range. Colour-coded on the watchlist for quick scanning.

Fyers only, since Yahoo doesn't provide reliable intraday data for Indian
equities. When the caller isn't connected to Fyers, endpoints return no data.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import MongoClient

from app.config import get_settings
from app.schemas.stock import IntradaySnapshot, TradeSetup
from app.services import fyers_client
from app.services.fyers_client import FyersError, FyersTokenExpired

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_OPENING_RANGE_CANDLES = 4  # 4 x 5-min = first 20 minutes (9:15-9:35 IST)
_FINE_RESOLUTION_SECS = 180  # 3-min candles post-9:35 for finer trigger detection
_CACHE_TTL_SECONDS = 60

_sync_mongo_client: MongoClient | None = None


def _trigger_collection():
    """Sync (pymongo) collection handle — `compute_snapshot` runs in a worker
    thread outside the asyncio loop, so it can't use the app's Motor client.

    A short server-selection timeout keeps a Mongo hiccup from stalling
    snapshot computation for pymongo's 30s default — callers fall back to
    in-memory-only freezing (see `_TriggerStateCache`) if this raises.
    """
    global _sync_mongo_client
    if _sync_mongo_client is None:
        settings = get_settings()
        _sync_mongo_client = MongoClient(
            settings.mongo_uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000,
        )
    settings = get_settings()
    try:
        db = _sync_mongo_client.get_default_database()
    except Exception:
        db = _sync_mongo_client[settings.mongo_db_name]
    return db.intraday_triggers


class _SnapshotCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, symbol: str) -> IntradaySnapshot | None:
        now = time.time()
        with self._lock:
            hit = self._store.get(symbol)
            if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
                return hit[1]
        return None

    def set(self, symbol: str, snapshot: IntradaySnapshot | None) -> None:
        if snapshot is None:
            return  # never poison the cache with a failure
        with self._lock:
            self._store[symbol] = (time.time(), snapshot)


_cache = _SnapshotCache()


class _TriggerStateCache:
    """Freezes the first trigger detected for a symbol each trading day.

    `compute_snapshot` re-fetches candles every `_CACHE_TTL_SECONDS`, and the
    monitor bar set (3-min vs 5-min fallback) can shift between calls — without
    freezing, that reshuffling made `triggeredAt` (and even the action) drift
    on every refresh. Once triggered, both are locked in until the next
    trading day, and the notifier is told to fire exactly once.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, symbol: str, today: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._store.get(symbol)
            if state is not None and state["date"] == today:
                return state

        # Not in this process's memory — check Mongo (survives --reload
        # restarts and is shared across worker processes).
        try:
            doc = _trigger_collection().find_one({"symbol": symbol, "date": today})
        except Exception:
            logger.exception("failed to read persisted trigger state for %s", symbol)
            return None
        if doc is None:
            return None
        state = self._state_from_doc(doc)
        with self._lock:
            self._store[symbol] = state
        return state

    @staticmethod
    def _state_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
        # pymongo returns naive datetimes (BSON stores UTC but drops tzinfo on read) —
        # reattach it, otherwise the frontend misreads the ISO string as local time.
        sl_hit_at = doc.get("slHitAt")
        return {
            "date": doc["date"],
            "triggered_at": doc["triggeredAt"].replace(tzinfo=timezone.utc),
            "action": doc["action"],
            "sl_hit_at": sl_hit_at.replace(tzinfo=timezone.utc) if sl_hit_at is not None else None,
        }

    def freeze(self, symbol: str, today: str, triggered_at: datetime, action: str) -> dict[str, Any]:
        with self._lock:
            state = self._store.get(symbol)
            if state is not None and state["date"] == today:
                return state

        # First writer wins even across processes/threads — $setOnInsert only
        # applies on the initial insert, so a concurrent freeze can't overwrite
        # an already-persisted trigger with a later timestamp.
        try:
            _trigger_collection().update_one(
                {"symbol": symbol, "date": today},
                {"$setOnInsert": {"triggeredAt": triggered_at, "action": action}},
                upsert=True,
            )
            doc = _trigger_collection().find_one({"symbol": symbol, "date": today})
        except Exception:
            logger.exception("failed to persist trigger state for %s — freezing in-memory only", symbol)
            doc = None

        state = (
            self._state_from_doc(doc)
            if doc is not None
            else {"date": today, "triggered_at": triggered_at, "action": action, "sl_hit_at": None}
        )

        with self._lock:
            self._store[symbol] = state
        return state

    def freeze_sl_hit(self, symbol: str, today: str, sl_hit_at: datetime) -> dict[str, Any] | None:
        """Locks in the stop-loss-hit timestamp exactly once per symbol/day.

        Uses a conditional update (`slHitAt` must not already exist) so
        concurrent pollers can't stomp on an already-recorded hit."""
        try:
            _trigger_collection().update_one(
                {"symbol": symbol, "date": today, "slHitAt": {"$exists": False}},
                {"$set": {"slHitAt": sl_hit_at}},
            )
            doc = _trigger_collection().find_one({"symbol": symbol, "date": today})
        except Exception:
            logger.exception("failed to persist SL-hit state for %s", symbol)
            return None
        if doc is None:
            return None
        state = self._state_from_doc(doc)
        with self._lock:
            self._store[symbol] = state
        return state


_trigger_state = _TriggerStateCache()



def _today_ist_date() -> str:
    return datetime.now(IST).date().isoformat()


def _build_trade_setup(
    *,
    current_price: float,
    orb_high: float,
    orb_low: float,
    vwap: float,
    trend: str,
    range_forming: bool = False,
    triggered_at: datetime | None = None,
    sl_hit_at: datetime | None = None,
) -> TradeSetup:
    """Turn the ORB numbers into a concrete plan: entry, SL, target, R:R."""
    vwap_tolerance = max(vwap * 0.001, 0.05)  # 0.1% or 5 paise, whichever bigger
    if abs(current_price - vwap) <= vwap_tolerance:
        vwap_position = "at"
    elif current_price > vwap:
        vwap_position = "above"
    else:
        vwap_position = "below"

    if range_forming:
        action = "wait"
        bias = "neutral"
        entry = current_price
        stop_loss = orb_low if current_price >= vwap else orb_high
        target = orb_high if current_price >= vwap else orb_low
        rationale = (
            f"Opening range still forming (₹{orb_low:.2f}–₹{orb_high:.2f}). "
            f"Wait until 9:35 IST for the range to lock, then trade the breakout. "
            f"Currently {vwap_position} VWAP ₹{vwap:.2f}."
        )
    elif trend == "up":
        action = "buy"
        bias = "bullish"
        entry = orb_high
        stop_loss = orb_low
        target = orb_high + (orb_high - orb_low)  # 1R projection above breakout
        vwap_note = (
            "aligned with VWAP" if vwap_position == "above" else "against VWAP (weaker signal)"
        )
        rationale = (
            f"Breakout long above swing high ₹{orb_high:.2f}. "
            f"Stop below swing low ₹{orb_low:.2f}. "
            f"Price is {vwap_position} VWAP ₹{vwap:.2f} — {vwap_note}."
        )
    elif trend == "down":
        action = "sell"
        bias = "bearish"
        entry = orb_low
        stop_loss = orb_high
        target = orb_low - (orb_high - orb_low)
        vwap_note = (
            "aligned with VWAP" if vwap_position == "below" else "against VWAP (weaker signal)"
        )
        rationale = (
            f"Breakdown short below swing low ₹{orb_low:.2f}. "
            f"Stop above swing high ₹{orb_high:.2f}. "
            f"Price is {vwap_position} VWAP ₹{vwap:.2f} — {vwap_note}."
        )
    else:
        action = "wait"
        bias = "neutral"
        entry = current_price
        stop_loss = orb_low if current_price >= vwap else orb_high
        target = orb_high if current_price >= vwap else orb_low
        rationale = (
            f"Price still inside opening range ₹{orb_low:.2f}–₹{orb_high:.2f}. "
            f"Wait for a decisive break. Currently {vwap_position} VWAP ₹{vwap:.2f}."
        )

    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    return TradeSetup(
        action=action,  # type: ignore[arg-type]
        bias=bias,  # type: ignore[arg-type]
        entry=round(entry, 2),
        stopLoss=round(stop_loss, 2),
        target=round(target, 2),
        riskRewardRatio=rr,
        vwapPosition=vwap_position,  # type: ignore[arg-type]
        rationale=rationale,
        triggeredAt=triggered_at,
        slHitAt=sl_hit_at,
    )


def compute_snapshot(symbol: str, access_token: str) -> IntradaySnapshot | None:
    """Fetch today's 5-min candles and reduce them to an ORB + VWAP snapshot.

    Returns None if Fyers can't be reached, market has no candles yet, or
    the token has expired.
    """
    symbol = symbol.upper()
    cached = _cache.get(symbol)
    if cached is not None:
        return cached

    today = _today_ist_date()

    # 5-min candles are used ONLY for defining the ORB high/low from the first 20 min.
    # 3-min candles power everything after 9:35 (VWAP, current price, trigger detection)
    # for finer resolution. Both calls are safe under Fyers' ~10 req/s limit.
    try:
        resp_5m = fyers_client.get_history(
            access_token, symbol, resolution="5", date_from=today, date_to=today,
        )
    except FyersTokenExpired:
        raise
    except FyersError as exc:
        logger.warning("Intraday 5m fetch failed for %s: %s", symbol, exc)
        return None

    # 3-min is optional — a rate-limit failure here shouldn't kill the whole snapshot.
    resp_3m: dict | None = None
    try:
        resp_3m = fyers_client.get_history(
            access_token, symbol, resolution="3", date_from=today, date_to=today,
        )
    except FyersTokenExpired:
        raise
    except FyersError as exc:
        logger.info("Intraday 3m fetch skipped for %s (falling back to 5m): %s", symbol, exc)

    candles_5m = _parse_candles(resp_5m.get("candles") or [])
    candles_3m = _parse_candles((resp_3m or {}).get("candles") or [])
    if not candles_5m:
        return None

    # ORB is always derived from the 5-min bars — a fixed contract with the trader.
    orb = candles_5m[:_OPENING_RANGE_CANDLES]
    if len(orb) == 0:
        return None
    # Skip the first 5-min candle: opening-auction spike and gap fills are noise.
    swing_pool = orb[1:] if len(orb) > 1 else orb
    swing_high_candle = max(swing_pool, key=lambda c: c["high"])
    swing_low_candle = min(swing_pool, key=lambda c: c["low"])
    orb_high = swing_high_candle["high"]
    orb_low = swing_low_candle["low"]
    orb_close = orb[-1]["close"]
    swing_complete = len(orb) >= _OPENING_RANGE_CANDLES
    swing_high_at = datetime.fromtimestamp(swing_high_candle["ts"] + 300, tz=timezone.utc)
    swing_low_at = datetime.fromtimestamp(swing_low_candle["ts"] + 300, tz=timezone.utc)

    # Post-ORB monitoring: prefer 3-min bars when available; otherwise fall back to 5-min.
    monitor = candles_3m if candles_3m else candles_5m

    total_pv = 0.0
    total_v = 0.0
    for c in monitor:
        typical_price = (c["high"] + c["low"] + c["close"]) / 3
        total_pv += typical_price * c["volume"]
        total_v += c["volume"]
    vwap = total_pv / total_v if total_v > 0 else monitor[-1]["close"]

    current_price = monitor[-1]["close"]
    day_high = max(c["high"] for c in monitor)
    day_low = min(c["low"] for c in monitor)

    if current_price > orb_high:
        trend = "up"
    elif current_price < orb_low:
        trend = "down"
    else:
        trend = "flat"

    # Before the ORB window closes at 9:35 IST, ORB high/low are still in flux.
    setup_trend = trend if swing_complete else "flat"

    # Scan the finer monitor bars for the first cross beyond the ORB high/low.
    # We only consider bars whose timestamp is at or after 9:35 (ORB close).
    orb_close_ts = orb[-1]["ts"] + 300  # start of bar 4 + 5 min = 9:35 IST epoch
    triggered_at: datetime | None = None
    trigger_bar_secs = _FINE_RESOLUTION_SECS if candles_3m else 300

    frozen = _trigger_state.get(symbol, today)
    if frozen is not None:
        # Already triggered earlier today — keep the original action + timestamp
        # constant regardless of how the monitor bar set reshuffles on refresh.
        setup_trend = frozen["action"]
        triggered_at = frozen["triggered_at"]
    elif swing_complete and setup_trend in ("up", "down"):
        for c in monitor:
            if c["ts"] < orb_close_ts:
                continue
            if setup_trend == "up" and c["high"] > orb_high:
                triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                break
            if setup_trend == "down" and c["low"] < orb_low:
                triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                break
        if triggered_at is not None:
            frozen = _trigger_state.freeze(symbol, today, triggered_at, setup_trend)
            triggered_at = frozen["triggered_at"]
            setup_trend = frozen["action"]

    # Once triggered, watch for the stop-loss level being breached — freezes
    # exactly once per symbol/day, same pattern as the trigger itself, so the
    # caller can fire a single "stop-loss hit, trade failed" alert.
    sl_hit_at: datetime | None = frozen["sl_hit_at"] if frozen is not None else None
    if frozen is not None and sl_hit_at is None and triggered_at is not None:
        stop_loss = orb_low if setup_trend == "buy" else orb_high
        sl_trigger_ts = triggered_at.timestamp() - trigger_bar_secs
        for c in monitor:
            if c["ts"] < sl_trigger_ts:
                continue
            if setup_trend == "buy" and c["low"] < stop_loss:
                sl_hit_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                break
            if setup_trend == "sell" and c["high"] > stop_loss:
                sl_hit_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                break
        if sl_hit_at is not None:
            updated = _trigger_state.freeze_sl_hit(symbol, today, sl_hit_at)
            if updated is not None:
                sl_hit_at = updated["sl_hit_at"]

    trade_setup = _build_trade_setup(
        current_price=current_price,
        orb_high=orb_high,
        orb_low=orb_low,
        vwap=vwap,
        trend=setup_trend,
        range_forming=not swing_complete,
        triggered_at=triggered_at,
        sl_hit_at=sl_hit_at,
    )

    snapshot = IntradaySnapshot(
        symbol=symbol,
        currentPrice=round(current_price, 2),
        openingRangeHigh=round(orb_high, 2),
        openingRangeLow=round(orb_low, 2),
        openingRangeClose=round(orb_close, 2),
        swingHighAt=swing_high_at,
        swingLowAt=swing_low_at,
        swingComplete=swing_complete,
        vwap=round(vwap, 2),
        dayHigh=round(day_high, 2),
        dayLow=round(day_low, 2),
        trend=trend,  # type: ignore[arg-type]
        candleCount=len(monitor),
        tradeSetup=trade_setup,
        updatedAt=datetime.now(timezone.utc),
    )
    _cache.set(symbol, snapshot)
    return snapshot


def _parse_candles(raw_candles: list) -> list[dict[str, float]]:
    parsed: list[dict[str, float]] = []
    for row in raw_candles:
        if len(row) < 6:
            continue
        try:
            parsed.append(
                {
                    "ts": float(row[0]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (TypeError, ValueError):
            continue
    return parsed
