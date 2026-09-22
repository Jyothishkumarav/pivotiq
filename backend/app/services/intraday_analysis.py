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
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import MongoClient

from app.config import get_settings
from app.schemas.stock import IntradaySnapshot, TradeSetup
from app.services import fyers_client, market_data
from app.services.fyers_client import FyersError, FyersTokenExpired

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_OPENING_RANGE_CANDLES = 4  # 4 x 5-min = first 20 minutes (9:15-9:35 IST)
_FINE_RESOLUTION_SECS = 180  # 3-min candles post-9:35 for finer trigger detection

# No FRESH trade entries past this IST wall-clock time, for every strategy —
# intraday square-off is 15:15 IST, so anything triggering this late leaves
# no room to manage the trade. Already-triggered setups keep being monitored
# for stop-loss hits right up to close; only *new* entries are blocked.
_NO_NEW_ENTRY_IST_TIME = dt_time(14, 45)


def _entry_cutoff_ts(today: str) -> float:
    """Epoch timestamp for 14:45 IST on `today` (YYYY-MM-DD)."""
    cutoff = datetime.strptime(today, "%Y-%m-%d").replace(
        hour=_NO_NEW_ENTRY_IST_TIME.hour, minute=_NO_NEW_ENTRY_IST_TIME.minute, tzinfo=IST,
    )
    return cutoff.timestamp()


# --- ORB + VWAP (default) only: gap-up/gap-down opening-conviction override ---
# If today gapped meaningfully AND the very first 5-min candle was a strong,
# well-supported candle in that same direction with real volume behind it,
# real demand/supply showed up at the open — a later dip back into that first
# candle's own range (which can still poke through the ORB low/high, since the
# ORB pool itself excludes candle 1) isn't a genuine breakdown/breakout, just
# a revisit of the open. Lock the setup to that direction for the rest of the
# day instead of ever flipping the opposite way. `context_gated` already has
# its own, more elaborate version of this idea — this is intentionally the
# simple, `orb_vwap`-only version and never touches the pluggable path.
_GAP_BIAS_MIN_CANDLES = 6  # need the first 30 min (6 x 5-min bars) before locking this in
_GAP_BIAS_MIN_MOVE_PCT = 0.5  # the first candle's own open→close move must clear this % on its own
_GAP_BIAS_BODY_FRACTION = 0.5  # candle body must be at least this fraction of its own high-low range
_GAP_BIAS_CLOSE_POSITION = 0.6  # close must sit in the outer 40% of the candle's range, in the gap's direction


def _orb_vwap_gap_bias(symbol: str, candles_5m: list[dict]) -> str | None:
    """Returns "buy"/"sell" once the first candle shows a strong, well-
    supported directional thrust with real volume behind it, else None (no
    override — `orb_vwap` behaves exactly as before).

    Deliberately gated on the candle's OWN open→close move rather than the
    prior-day gap: on this data feed a stock can print a big, obviously
    one-sided first candle (e.g. RRKABEL rallying ~1.8% in the first 5
    minutes on 3x normal volume) even when the raw overnight gap classifies
    as flat — that thrust is still real, tradeable conviction."""
    if len(candles_5m) < _GAP_BIAS_MIN_CANDLES:
        return None

    first = candles_5m[0]
    if first["open"] <= 0:
        return None
    candle_range = first["high"] - first["low"]
    if candle_range <= 0:
        return None

    move_pct = ((first["close"] - first["open"]) / first["open"]) * 100
    body = first["close"] - first["open"]
    close_position = (first["close"] - first["low"]) / candle_range
    body_fraction = abs(body) / candle_range

    rest = candles_5m[1:_GAP_BIAS_MIN_CANDLES]
    avg_rest_vol = sum(c["volume"] for c in rest) / len(rest) if rest else 0.0
    good_volume = avg_rest_vol <= 0 or first["volume"] > avg_rest_vol

    is_strong_green = (
        body > 0 and body_fraction >= _GAP_BIAS_BODY_FRACTION and close_position >= _GAP_BIAS_CLOSE_POSITION
    )
    is_strong_red = (
        body < 0 and body_fraction >= _GAP_BIAS_BODY_FRACTION and close_position <= 1 - _GAP_BIAS_CLOSE_POSITION
    )

    if move_pct > _GAP_BIAS_MIN_MOVE_PCT and is_strong_green and good_volume:
        return "buy"
    if move_pct < -_GAP_BIAS_MIN_MOVE_PCT and is_strong_red and good_volume:
        return "sell"
    return None


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


class _CandlesCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, list[dict[str, float]]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float) -> list[dict[str, float]] | None:
        now = time.time()
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and now - hit[0] < ttl:
                return hit[1]
        return None

    def set(self, key: str, candles: list[dict[str, float]]) -> None:
        if not candles:
            return
        with self._lock:
            self._store[key] = (time.time(), candles)


_candles_cache = _CandlesCache()


def invalidate_snapshot_cache(
    *,
    strategy: str,
    symbols: list[str] | None = None,
) -> int:
    """Evict entries from the in-memory snapshot cache.

    Matches keys of the form ``{SYMBOL}:{strategy}:{entry_mode}``.
    Returns the number of cache entries evicted.
    """
    evicted = 0
    with _cache._lock:
        keys_to_drop = [
            k for k in list(_cache._store.keys())
            if f":{strategy}:" in k
            and (symbols is None or any(k.startswith(s.upper() + ":") for s in symbols))
        ]
        for k in keys_to_drop:
            del _cache._store[k]
            evicted += 1
    return evicted


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

    def get(
        self, symbol: str, today: str, strategy: str = "orb_vwap", entry_mode: str = "close", include_first_candle: bool = False,
    ) -> dict[str, Any] | None:
        key = f"{symbol}:{strategy}:{entry_mode}:{int(include_first_candle)}"
        with self._lock:
            state = self._store.get(key)
            if state is not None and state["date"] == today:
                return state

        # Not in this process's memory — check Mongo (survives --reload
        # restarts and is shared across worker processes).
        try:
            doc = _trigger_collection().find_one(_strategy_filter(symbol, today, strategy, entry_mode, include_first_candle))
        except Exception:
            logger.exception("failed to read persisted trigger state for %s", symbol)
            return None
        if doc is None:
            return None
        state = self._state_from_doc(doc)
        with self._lock:
            self._store[key] = state
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
            "entry": doc.get("entry"),
            "stop_loss": doc.get("stopLoss"),
            "sl_wide": doc.get("slWide"),
            "confirmation": doc.get("confirmation"),
            "trigger_price": doc.get("triggerPrice"),
            "entry_mode": doc.get("entryMode", "close"),
            "include_first_candle": doc.get("includeFirstCandle", False),
        }

    def freeze(
        self,
        symbol: str,
        today: str,
        triggered_at: datetime,
        action: str,
        strategy: str = "orb_vwap",
        entry_mode: str = "close",
        include_first_candle: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = f"{symbol}:{strategy}:{entry_mode}:{int(include_first_candle)}"
        with self._lock:
            state = self._store.get(key)
            if state is not None and state["date"] == today:
                return state

        # First writer wins even across processes/threads — $setOnInsert only
        # applies on the initial insert, so a concurrent freeze can't overwrite
        # an already-persisted trigger with a later timestamp.
        try:
            insert_fields = {
                "symbol": symbol,
                "date": today,
                "strategy": strategy,
                "entryMode": entry_mode,
                "includeFirstCandle": include_first_candle,
                "triggeredAt": triggered_at,
                "action": action,
                **(extra or {}),
            }
            query = {
                "symbol": symbol,
                "date": today,
                "strategy": strategy,
                "entryMode": entry_mode,
                "includeFirstCandle": include_first_candle,
            }
            _trigger_collection().update_one(
                query,
                {"$setOnInsert": insert_fields},
                upsert=True,
            )
            doc = _trigger_collection().find_one(query)
        except Exception:
            logger.exception("failed to persist trigger state for %s — freezing in-memory only", symbol)
            doc = None

        state = (
            self._state_from_doc(doc)
            if doc is not None
            else {
                "date": today, "triggered_at": triggered_at, "action": action, "sl_hit_at": None,
                "entry": (extra or {}).get("entry"), "stop_loss": (extra or {}).get("stopLoss"),
                "sl_wide": (extra or {}).get("slWide"),
                "confirmation": (extra or {}).get("confirmation"),
                "trigger_price": (extra or {}).get("triggerPrice"),
                "entry_mode": entry_mode,
                "include_first_candle": include_first_candle,
            }
        )

        with self._lock:
            self._store[key] = state
        return state

    def freeze_sl_hit(
        self, symbol: str, today: str, sl_hit_at: datetime, strategy: str = "orb_vwap", entry_mode: str = "close", include_first_candle: bool = False,
    ) -> dict[str, Any] | None:
        """Locks in the stop-loss-hit timestamp exactly once per symbol/day.

        Uses a conditional update (`slHitAt` must not already exist) so
        concurrent pollers can't stomp on an already-recorded hit."""
        try:
            query = {
                "symbol": symbol,
                "date": today,
                "strategy": strategy,
                "entryMode": entry_mode,
                "includeFirstCandle": include_first_candle,
                "slHitAt": {"$exists": False},
            }
            res = _trigger_collection().update_one(query, {"$set": {"slHitAt": sl_hit_at}})
            if res.matched_count == 0 and not include_first_candle:
                fallback_query = {
                    "symbol": symbol,
                    "date": today,
                    "strategy": strategy,
                    "entryMode": entry_mode,
                    "includeFirstCandle": {"$exists": False},
                    "slHitAt": {"$exists": False},
                }
                _trigger_collection().update_one(fallback_query, {"$set": {"slHitAt": sl_hit_at}})
            doc = _trigger_collection().find_one(_strategy_filter(symbol, today, strategy, entry_mode, include_first_candle))
        except Exception:
            logger.exception("failed to persist SL-hit state for %s", symbol)
            return None
        if doc is None:
            return None
        state = self._state_from_doc(doc)
        with self._lock:
            self._store[f"{symbol}:{strategy}:{entry_mode}:{int(include_first_candle)}"] = state
        return state


_trigger_state = _TriggerStateCache()


def _strategy_filter(
    symbol: str, today: str, strategy: str, entry_mode: str = "close", include_first_candle: bool = False,
) -> dict[str, Any]:
    filter_dict: dict[str, Any] = {
        "symbol": symbol,
        "date": today,
        "strategy": strategy,
    }
    if entry_mode == "close":
        filter_dict["$or"] = [{"entryMode": "close"}, {"entryMode": {"$exists": False}}]
    else:
        filter_dict["entryMode"] = entry_mode

    if not include_first_candle:
        filter_dict["includeFirstCandle"] = {"$in": [False, None]}
    else:
        filter_dict["includeFirstCandle"] = True
    return filter_dict


def get_trigger_collection():
    """Public accessor so pluggable strategy modules can persist their own
    trigger/SL-hit state through the same Mongo collection."""
    return _trigger_collection()


def clear_frozen_triggers(
    *,
    strategy: str,
    date: str | None = None,
    symbols: list[str] | None = None,
) -> int:
    """Delete frozen trigger records from Mongo + wipe matching in-memory cache keys.

    Args:
        strategy:  e.g. 'orb_pullback_support'
        date:      ISO date string (YYYY-MM-DD). If None, deletes ALL dates for this strategy.
        symbols:   List of symbols to clear. If None, clears ALL symbols for this strategy/date.

    Returns the number of Mongo documents deleted.
    """
    query: dict[str, Any] = {"strategy": strategy}
    if date is not None:
        query["date"] = date
    if symbols:
        query["symbol"] = {"$in": [s.upper() for s in symbols]}

    try:
        result = _trigger_collection().delete_many(query)
        deleted = result.deleted_count
    except Exception:
        logger.exception("clear_frozen_triggers: failed to delete from Mongo")
        deleted = 0

    # Also evict matching keys from the in-memory cache so the next
    # compute_snapshot call re-evaluates from raw candles immediately.
    with _trigger_state._lock:
        keys_to_drop = [
            k for k in list(_trigger_state._store.keys())
            if f":{strategy}:" in k
            and (symbols is None or any(k.startswith(s.upper() + ":") for s in symbols))
        ]
        for k in keys_to_drop:
            del _trigger_state._store[k]

    logger.info(
        "clear_frozen_triggers: strategy=%s date=%s symbols=%s → %d DB docs deleted, %d cache keys evicted",
        strategy, date, symbols, deleted, len(keys_to_drop),
    )
    return deleted


def _today_ist_date() -> str:
    return datetime.now(IST).date().isoformat()


def _latest_trading_date() -> str:
    """Return today's date in IST, or the latest completed trading session date
    if today is a weekend or before market open (09:15 IST)."""
    now_ist = datetime.now(IST)
    d = now_ist.date()
    if now_ist.weekday() == 5:  # Saturday -> Friday
        d = d - timedelta(days=1)
    elif now_ist.weekday() == 6:  # Sunday -> Friday
        d = d - timedelta(days=2)
    elif now_ist.time() < dt_time(9, 15):
        # Weekday before 09:15 open -> prior trading day
        if now_ist.weekday() == 0:  # Monday morning -> Friday
            d = d - timedelta(days=3)
        else:
            d = d - timedelta(days=1)
    return d.isoformat()


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
    lean: str | None = None,
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
        # No ORB yet to break — lean buy/sell off the gap-bias override (if any),
        # else VWAP, so `action` is always a real direction; `status` (below)
        # is what actually tells the caller nothing has triggered yet.
        action = lean if lean is not None else ("buy" if current_price >= vwap else "sell")
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
        action = lean if lean is not None else ("buy" if current_price >= vwap else "sell")
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

    status = "sl_hit" if sl_hit_at is not None else "triggered" if triggered_at is not None else "waiting"

    return TradeSetup(
        action=action,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
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


def compute_snapshot(
    symbol: str,
    access_token: str,
    strategy: str = "orb_vwap",
    entry_mode: str = "close",
    retest_date: str | None = None,
    include_first_candle: bool = False,
) -> IntradaySnapshot | None:
    """Fetch candles and reduce them to an ORB snapshot.

    `strategy` selects which pluggable trade-setup logic builds the
    `tradeSetup` field.
    `retest_date` when supplied runs in read-only retest mode on historical
    candles for that specific ISO date (YYYY-MM-DD), skipping Mongo state
    writes and telegram alerts.

    Returns None if Fyers can't be reached, market has no candles yet, or
    the token has expired.
    """
    symbol = symbol.upper()
    is_retest = bool(retest_date)
    cache_key = f"{symbol}:{strategy}:{entry_mode}:{int(include_first_candle)}:{retest_date or 'live'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    today = retest_date if is_retest else _latest_trading_date()
    candles_ttl = 86400.0 if is_retest else 45.0
    key_5m = f"{symbol}:5m:{today}"
    key_3m = f"{symbol}:3m:{today}"

    candles_5m = _candles_cache.get(key_5m, candles_ttl)
    if candles_5m is None:
        try:
            resp_5m = fyers_client.get_history(
                access_token, symbol, resolution="5", date_from=today, date_to=today,
            )
        except FyersTokenExpired:
            raise
        except FyersError as exc:
            logger.warning("Intraday 5m fetch failed for %s on %s: %s", symbol, today, exc)
            return None

        candles_5m = _parse_candles(resp_5m.get("candles") or [])

        # In live mode: if candidate date has no trading bars (holiday during weekday),
        # step back to the prior business day so users can still see the last active session.
        # In retest mode: do not step back; return None if the requested historical date has no data.
        if not candles_5m and not is_retest:
            prev_d = datetime.fromisoformat(today).date() - timedelta(days=1)
            while prev_d.weekday() >= 5:
                prev_d -= timedelta(days=1)
            prev_str = prev_d.isoformat()
            try:
                resp_5m_prev = fyers_client.get_history(
                    access_token, symbol, resolution="5", date_from=prev_str, date_to=prev_str,
                )
                parsed_prev = _parse_candles(resp_5m_prev.get("candles") or [])
                if parsed_prev:
                    today = prev_str
                    candles_5m = parsed_prev
                    key_5m = f"{symbol}:5m:{today}"
                    key_3m = f"{symbol}:3m:{today}"
            except Exception:
                pass

        if not candles_5m:
            return None
        _candles_cache.set(key_5m, candles_5m)

    candles_3m = _candles_cache.get(key_3m, candles_ttl)
    if candles_3m is None:
        resp_3m: dict | None = None
        try:
            resp_3m = fyers_client.get_history(
                access_token, symbol, resolution="3", date_from=today, date_to=today,
            )
        except FyersTokenExpired:
            raise
        except FyersError as exc:
            logger.info("Intraday 3m fetch skipped for %s (falling back to 5m): %s", symbol, exc)

        candles_3m = _parse_candles((resp_3m or {}).get("candles") or [])
        if candles_3m:
            _candles_cache.set(key_3m, candles_3m)

    # ORB is derived from the 5-min bars:
    # 4 x 5-min candles = first 20 min (9:15-9:35 IST) for all strategies.
    orb = candles_5m[:_OPENING_RANGE_CANDLES]
    if len(orb) == 0:
        return None
    # If include_first_candle is True (only applicable to pluggable strategies like orb_pullback_support):
    # include opening candle in swing pool.
    # For orb_vwap, always skip the first candle to determine heights.
    if include_first_candle and strategy != "orb_vwap":
        swing_pool = orb
    else:
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

    # Before the ORB window closes at 9:35 IST, ORB high/low are in flux.
    setup_trend = trend if swing_complete else "flat"

    # Strong, well-supported gap-open locks out the opposite direction
    # for the rest of the day — see `_orb_vwap_gap_bias` docstring.
    gap_bias = _orb_vwap_gap_bias(symbol, candles_5m)
    if gap_bias == "buy" and setup_trend == "down":
        setup_trend = "flat"
    elif gap_bias == "sell" and setup_trend == "up":
        setup_trend = "flat"

    # Scan the finer monitor bars for the first cross beyond the ORB high/low at or after 9:35.
    orb_close_ts = orb[-1]["ts"] + 300  # start of post-ORB window epoch (9:35 IST)
    triggered_at: datetime | None = None
    trigger_bar_secs = _FINE_RESOLUTION_SECS if candles_3m else 300
    entry_cutoff_ts = _entry_cutoff_ts(today)

    prev_close: float | None = None
    change_pct: float | None = None
    if not is_retest:
        live_quote = market_data.get_quote(symbol, access_token=access_token)
        if live_quote is not None:
            if live_quote.ltp:
                current_price = live_quote.ltp
            prev_close = live_quote.prevClose
            change_pct = live_quote.changePercent

    if change_pct is None and candles_5m and candles_5m[0].get("open"):
        first_open = candles_5m[0]["open"]
        prev_close = first_open
        change_pct = round(((current_price - first_open) / first_open) * 100, 2)

    if strategy != "orb_vwap":
        trade_setup = _compute_pluggable_setup(
            strategy=strategy,
            symbol=symbol,
            today=today,
            candles_5m=candles_5m,
            monitor=monitor,
            orb_high=orb_high,
            orb_low=orb_low,
            orb_close_ts=orb_close_ts,
            vwap=vwap,
            current_price=current_price,
            trigger_bar_secs=trigger_bar_secs,
            entry_cutoff_ts=entry_cutoff_ts,
            entry_mode=entry_mode,
            include_first_candle=include_first_candle,
            is_retest=is_retest,
            setup_trend=setup_trend,
            gap_bias=gap_bias,
        )
    else:
        frozen = _trigger_state.get(symbol, today, entry_mode=entry_mode, include_first_candle=False) if not is_retest else None
        if frozen is not None:
            # Already triggered earlier today — keep the original action + timestamp
            # constant regardless of how the monitor bar set reshuffles on refresh.
            setup_trend = frozen["action"]
            triggered_at = frozen["triggered_at"]
        elif swing_complete:
            allow_up = gap_bias != "sell"
            allow_down = gap_bias != "buy"
            for c in monitor:
                if c["ts"] < orb_close_ts:
                    continue
                if c["ts"] >= entry_cutoff_ts:
                    break  # no fresh entries past 14:45 IST
                broke_high = c["close"] > orb_high if entry_mode == "close" else c["high"] > orb_high
                broke_low = c["close"] < orb_low if entry_mode == "close" else c["low"] < orb_low
                if broke_high and broke_low:
                    if allow_up and (gap_bias == "buy" or c["close"] >= c["open"]):
                        setup_trend = "up"
                        triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                        break
                    elif allow_down:
                        setup_trend = "down"
                        triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                        break
                    elif allow_up:
                        setup_trend = "up"
                        triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                        break
                elif broke_high and allow_up:
                    setup_trend = "up"
                    triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                    break
                elif broke_low and allow_down:
                    setup_trend = "down"
                    triggered_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                    break

            if triggered_at is not None and not is_retest:
                frozen = _trigger_state.freeze(symbol, today, triggered_at, setup_trend, entry_mode=entry_mode)
                triggered_at = frozen["triggered_at"]
                setup_trend = frozen["action"]

        # Once triggered, watch for the stop-loss level being breached across all monitor bars
        # right up to session close (including the final 30 minutes).
        sl_hit_at: datetime | None = frozen["sl_hit_at"] if frozen is not None else None
        if sl_hit_at is None and triggered_at is not None:
            stop_loss = orb_low if setup_trend in ("buy", "up") else orb_high
            sl_trigger_ts = triggered_at.timestamp() - trigger_bar_secs
            for c in monitor:
                if c["ts"] < sl_trigger_ts:
                    continue
                if setup_trend in ("buy", "up") and c["low"] < stop_loss:
                    sl_hit_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                    break
                if setup_trend in ("sell", "down") and c["high"] > stop_loss:
                    sl_hit_at = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                    break
            if sl_hit_at is not None and not is_retest:
                updated = _trigger_state.freeze_sl_hit(symbol, today, sl_hit_at, entry_mode=entry_mode)
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
            lean=gap_bias,
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
        retestDate=retest_date,
        prevClose=round(prev_close, 2) if prev_close is not None else None,
        changePercent=round(change_pct, 2) if change_pct is not None else None,
    )
    _cache.set(cache_key, snapshot)
    return snapshot


def _compute_pluggable_setup(
    strategy: str,
    symbol: str,
    today: str,
    candles_5m: list[dict],
    monitor: list[dict],
    orb_high: float,
    orb_low: float,
    orb_close_ts: float,
    vwap: float,
    current_price: float,
    trigger_bar_secs: int,
    entry_cutoff_ts: float,
    entry_mode: str = "close",
    include_first_candle: bool = False,
    is_retest: bool = False,
    setup_trend: str = "flat",
    gap_bias: str | None = None,
) -> TradeSetup:
    """Dispatches to a non-default strategy module, wiring its freeze/SL-hit
    state through the same shared `_trigger_state` cache (namespaced by
    `strategy`, `entry_mode`, and `include_first_candle` so it never collides).

    `entry_cutoff_ts` is forwarded so every strategy blocks FRESH entries
    past 14:45 IST the same way — already-triggered setups still get their
    SL monitored off the full `monitor` regardless (including the final 30 mins)."""
    if strategy == "context_gated":
        from app.services.strategies import context_gated

        frozen = _trigger_state.get(symbol, today, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle) if not is_retest else None
        setup, freeze_payload = context_gated.compute_setup(
            symbol=symbol,
            candles_5m=candles_5m,
            monitor=monitor,
            orb_high=orb_high,
            orb_low=orb_low,
            orb_close_ts=orb_close_ts,
            vwap=vwap,
            current_price=current_price,
            trigger_bar_secs=trigger_bar_secs,
            entry_cutoff_ts=entry_cutoff_ts,
            frozen=frozen,
        )
        if not is_retest and frozen is None and freeze_payload is not None:
            frozen = _trigger_state.freeze(
                symbol, today, freeze_payload["triggered_at"], freeze_payload["action"],
                strategy=strategy,
                entry_mode=entry_mode,
                include_first_candle=include_first_candle,
                extra={
                    "entry": freeze_payload["entry"],
                    "stopLoss": freeze_payload["stop_loss"],
                    "slWide": freeze_payload["sl_wide"],
                    "confirmation": freeze_payload["confirmation"],
                },
            )
            setup.triggeredAt = frozen["triggered_at"]
            setup.status = "triggered"

        sl_hit_at = frozen.get("sl_hit_at") if frozen is not None else None
        if sl_hit_at is None and setup.triggeredAt is not None:
            action = frozen["action"] if frozen is not None else setup.action
            stop_loss = frozen["stop_loss"] if frozen is not None else setup.stopLoss
            sl_hit_at = context_gated.check_sl_hit(
                monitor, action, stop_loss, setup.triggeredAt, trigger_bar_secs,
            )
            if sl_hit_at is not None:
                if not is_retest:
                    updated = _trigger_state.freeze_sl_hit(symbol, today, sl_hit_at, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle)
                    if updated is not None:
                        sl_hit_at = updated["sl_hit_at"]
                setup.slHitAt = sl_hit_at
                setup.status = "sl_hit"
        setup.includeFirstCandle = include_first_candle
        return setup

    if strategy == "orb_pullback":
        from app.services.strategies import orb_pullback

        frozen = _trigger_state.get(symbol, today, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle) if not is_retest else None
        setup, freeze_payload = orb_pullback.compute_setup(
            symbol=symbol,
            candles_5m=candles_5m,
            monitor=monitor,
            orb_high=orb_high,
            orb_low=orb_low,
            orb_close_ts=orb_close_ts,
            vwap=vwap,
            current_price=current_price,
            trigger_bar_secs=trigger_bar_secs,
            entry_cutoff_ts=entry_cutoff_ts,
            entry_mode=entry_mode,
            frozen=frozen,
        )
        if not is_retest and frozen is None and freeze_payload is not None:
            frozen = _trigger_state.freeze(
                symbol, today, freeze_payload["triggered_at"], freeze_payload["action"],
                strategy=strategy,
                entry_mode=entry_mode,
                include_first_candle=include_first_candle,
                extra={
                    "entry": freeze_payload["entry"],
                    "stopLoss": freeze_payload["stop_loss"],
                    "triggerPrice": freeze_payload["trigger_price"],
                },
            )
            setup.triggeredAt = frozen["triggered_at"]
            setup.status = "triggered"
            setup.triggerPrice = frozen.get("trigger_price")
        elif frozen is not None:
            setup.triggerPrice = frozen.get("trigger_price")

        if setup.triggeredAt is not None:
            action = frozen["action"] if frozen is not None else setup.action
            # Setup status (sl_hit) strictly depends on MSL (macro stop), not tight SL
            sl_to_check = (
                frozen.get("sl_wide")
                if (frozen is not None and frozen.get("sl_wide") is not None)
                else (setup.slWide if setup.slWide is not None else (frozen.get("stop_loss") if frozen is not None else setup.stopLoss))
            )
            msl_hit_at = orb_pullback.check_sl_hit(
                monitor, action, sl_to_check, setup.triggeredAt, trigger_bar_secs,
            )
            if msl_hit_at is not None:
                if not is_retest:
                    updated = _trigger_state.freeze_sl_hit(symbol, today, msl_hit_at, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle)
                    if updated is not None:
                        msl_hit_at = updated["sl_hit_at"]
                setup.slHitAt = msl_hit_at
                setup.status = "sl_hit"
            else:
                if frozen is not None and frozen.get("sl_hit_at") is not None:
                    try:
                        _trigger_collection().update_one(
                            _strategy_filter(symbol, today, strategy, entry_mode, include_first_candle),
                            {"$unset": {"slHitAt": ""}},
                        )
                        frozen["sl_hit_at"] = None
                    except Exception:
                        pass
                setup.slHitAt = None
                setup.status = "triggered"
        setup.includeFirstCandle = include_first_candle
        return setup

    if strategy == "orb_pullback_support":
        from app.services.strategies import orb_pullback_support

        frozen = _trigger_state.get(symbol, today, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle) if not is_retest else None
        setup, freeze_payload = orb_pullback_support.compute_setup(
            symbol=symbol,
            candles_5m=candles_5m,
            monitor=monitor,
            orb_high=orb_high,
            orb_low=orb_low,
            orb_close_ts=orb_close_ts,
            vwap=vwap,
            current_price=current_price,
            trigger_bar_secs=trigger_bar_secs,
            entry_cutoff_ts=entry_cutoff_ts,
            entry_mode=entry_mode,
            frozen=frozen,
            setup_trend=setup_trend,
            gap_bias=gap_bias,
        )
        if not is_retest and frozen is None and freeze_payload is not None:
            frozen = _trigger_state.freeze(
                symbol, today, freeze_payload["triggered_at"], freeze_payload["action"],
                strategy=strategy,
                entry_mode=entry_mode,
                include_first_candle=include_first_candle,
                extra={
                    "entry": freeze_payload["entry"],
                    "stopLoss": freeze_payload["stop_loss"],
                    "triggerPrice": freeze_payload["trigger_price"],
                    "slWide": freeze_payload.get("sl_wide"),
                },
            )
            setup.triggeredAt = frozen["triggered_at"]
            setup.status = "triggered"
            setup.triggerPrice = frozen.get("trigger_price")
        elif frozen is not None:
            setup.triggerPrice = frozen.get("trigger_price")

        if setup.triggeredAt is not None:
            action = frozen["action"] if frozen is not None else setup.action
            # Setup status (sl_hit) strictly depends on MSL (macro stop), not tight SL
            sl_to_check = (
                frozen.get("sl_wide")
                if (frozen is not None and frozen.get("sl_wide") is not None)
                else (setup.slWide if setup.slWide is not None else (frozen.get("stop_loss") if frozen is not None else setup.stopLoss))
            )
            msl_hit_at = orb_pullback_support.check_sl_hit(
                monitor, action, sl_to_check, setup.triggeredAt, trigger_bar_secs, entry_mode=entry_mode,
            )
            if msl_hit_at is not None:
                if not is_retest:
                    updated = _trigger_state.freeze_sl_hit(symbol, today, msl_hit_at, strategy=strategy, entry_mode=entry_mode, include_first_candle=include_first_candle)
                    if updated is not None:
                        msl_hit_at = updated["sl_hit_at"]
                setup.slHitAt = msl_hit_at
                setup.status = "sl_hit"
            else:
                # MSL was never breached. If a legacy record prematurely recorded tight-SL hit, self-heal and clear it:
                if frozen is not None and frozen.get("sl_hit_at") is not None:
                    try:
                        _trigger_collection().update_one(
                            _strategy_filter(symbol, today, strategy, entry_mode, include_first_candle),
                            {"$unset": {"slHitAt": ""}},
                        )
                        frozen["sl_hit_at"] = None
                    except Exception:
                        pass
                setup.slHitAt = None
                setup.status = "triggered"
        setup.includeFirstCandle = include_first_candle
        return setup

    raise ValueError(f"Unknown strategy: {strategy!r}")


def _parse_candles(raw_candles: list) -> list[dict[str, float]]:
    parsed: list[dict[str, float]] = []
    for row in raw_candles:
        if len(row) < 6:
            continue
        try:
            parsed.append(
                {
                    "ts": float(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (TypeError, ValueError):
            continue
    return parsed
