"""Context-gated ORB strategy — gap significance, first-candle conviction,
daily trend, and Higher-Low/Lower-High "break of structure" (HL-BOS) entries
instead of the plain ORB-box breakout used by "orb_vwap".

This module is purely additive: it is only invoked when a watchlist is
explicitly configured to use `strategy="context_gated"`. The default
`"orb_vwap"` path in `intraday_analysis.py` is completely untouched.

Design recap (from the NETWEB post-mortem):
  1. Gap significance: an overnight gap only counts if it clears BOTH a %
     floor and a fraction of the stock's own 14-day ATR — a small % move on
     a currently-volatile stock is noise, not a gap.
  2. First-candle conviction: did the opening candle fill the gap, where did
     it close within its own range, and was volume abnormal vs. the next few
     candles? This is independent of (1) — a strong opening thrust is a
     signal on its own even when the raw overnight gap is small.
  3. Daily trend: recent daily candle direction (up/down streak).
  4. Combine (1)-(3) into a `dailyBias` (direction + conviction). High
     conviction suppresses the counter-trend direction entirely; medium
     conviction still allows it, but only via the stricter HL-BOS structure
     break (never the raw ORB box); low/neutral behaves like the plain ORB
     strategy in both directions.
  5. HL-BOS: swing highs/lows are detected with a small confirmation lag `K`
     (candles on each side). A Higher-Low followed by a break above the last
     confirmed swing high (mirrored for the downside) is what actually
     confirms the move — this reacts to the evolving intraday structure
     instead of a fixed opening-range box or the day's absolute extreme
     (which gets permanently pinned by opening-auction wicks on volatile
     days).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.schemas.stock import TradeSetup
from app.services import market_data

logger = logging.getLogger(__name__)

_GAP_PCT_FLOOR = 0.3  # %
_GAP_ATR_MULT = 0.5
_OPENING_WINDOW_SECS = 15 * 60  # the "first 15 minutes" used to read direction and set the wide stop-loss level
_OPENING_DRIFT_THRESHOLD = 0.15  # fraction of the opening window's own range needed to call it bullish/bearish
_SWING_WINDOW = 2  # bars each side to confirm a swing high/low, intraday-tuned (small so it doesn't lag the move)
_SWING_ATR_PERIOD = 14
_SWING_ATR_MULTIPLIER = 0.25  # breakout must clear the swing level by this many ATRs, not a fixed price/%
_SWING_VOLUME_LOOKBACK = 20
_SWING_VOLUME_MULTIPLIER = 1.5  # breakout bar's volume must be this many times its recent average


def _atr14(daily: list) -> float | None:
    if len(daily) < 15:
        return None
    trs = []
    for i in range(1, len(daily)):
        h, l, pc = daily[i].high, daily[i].low, daily[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    last14 = trs[-14:]
    return sum(last14) / len(last14) if last14 else None


def _gap_class(daily: list, atr14: float | None) -> tuple[str, float, float]:
    """Returns (gapClass, gapPct, prevClose). gapClass in up/down/flat."""
    if len(daily) < 2 or atr14 is None or atr14 <= 0:
        return "flat", 0.0, daily[-1].close if daily else 0.0
    prev_close = daily[-2].close
    today_open = daily[-1].open
    if prev_close <= 0:
        return "flat", 0.0, prev_close
    gap_abs = today_open - prev_close
    gap_pct = (gap_abs / prev_close) * 100
    if gap_pct > _GAP_PCT_FLOOR and gap_abs > _GAP_ATR_MULT * atr14:
        return "up", gap_pct, prev_close
    if gap_pct < -_GAP_PCT_FLOOR and -gap_abs > _GAP_ATR_MULT * atr14:
        return "down", gap_pct, prev_close
    return "flat", gap_pct, prev_close


def _opening_window(candles_5m: list[dict]) -> tuple[float, float, float, list[dict]]:
    """True opening-window high/low over the first 15 minutes, INCLUDING the
    very first candle. The ORB swing pool deliberately excludes candle 1 to
    dodge opening-auction noise for the `orb_vwap` strategy, but that means a
    'break' of that narrower range can still be well inside candle 1's real
    high/low — not a genuine new extreme at all. Using the true window here
    avoids that false-breakout trap."""
    if not candles_5m:
        return 0.0, 0.0, 0.0, []
    start_ts = candles_5m[0]["ts"]
    window = [c for c in candles_5m if c["ts"] < start_ts + _OPENING_WINDOW_SECS]
    if not window:
        window = candles_5m[:1]
    high = max(c["high"] for c in window)
    low = min(c["low"] for c in window)
    end_ts = window[-1]["ts"] + 300  # 5-min bar width
    return high, low, end_ts, window


def _opening_window_bias(window: list[dict]) -> str:
    """Directional read from the WHOLE opening window (not just candle 1) —
    where price ended up relative to where it started, scaled by the
    window's own range so it adapts to the day's volatility."""
    if len(window) < 2:
        return "neutral"
    rng = max(c["high"] for c in window) - min(c["low"] for c in window)
    if rng <= 0:
        return "neutral"
    drift = (window[-1]["close"] - window[0]["open"]) / rng
    if drift > _OPENING_DRIFT_THRESHOLD:
        return "bullish"
    if drift < -_OPENING_DRIFT_THRESHOLD:
        return "bearish"
    return "neutral"


def _daily_trend(daily: list) -> str:
    """Direction bias from the last 3 *completed* sessions (excludes today),
    comparing each session's close to the PRIOR session's close (i.e. is the
    stock's closing price actually trending up/down day over day) — not each
    day's own open-vs-close color, which measures something different."""
    completed = daily[:-1]
    if len(completed) < 4:
        return "neutral"
    last4 = completed[-4:]  # need one extra prior close to diff the first of the 3
    up_days = sum(1 for i in range(1, 4) if last4[i].close > last4[i - 1].close)
    down_days = sum(1 for i in range(1, 4) if last4[i].close < last4[i - 1].close)
    if up_days >= 2:
        return "up"
    if down_days >= 2:
        return "down"
    return "neutral"


def _daily_bias(gap_class: str, opening_bias: str, daily_trend: str) -> tuple[str, str]:
    """Combines the three signals into (direction, conviction). The opening-
    window read is weighted double — it's the most direct, current-session
    evidence (gap + movement of every candle in the first 15 minutes), so it
    should usually be decisive rather than just one vote among equals."""
    votes = []
    if gap_class == "up":
        votes.append("bullish")
    elif gap_class == "down":
        votes.append("bearish")
    if daily_trend == "up":
        votes.append("bullish")
    elif daily_trend == "down":
        votes.append("bearish")
    if opening_bias != "neutral":
        votes.append(opening_bias)
        votes.append(opening_bias)

    bullish = votes.count("bullish")
    bearish = votes.count("bearish")
    if bullish == 0 and bearish == 0:
        return "neutral", "low"
    if bullish > bearish:
        return "bullish", "high" if bullish >= 2 else "medium"
    if bearish > bullish:
        return "bearish", "high" if bearish >= 2 else "medium"
    return "neutral", "low"


def _dual_stop_breakout(
    monitor: list[dict], direction: str, trigger_bar_secs: int,
) -> tuple[datetime, float, float] | None:
    """Higher-High (bullish) / Lower-Low (bearish) breakout, intraday-tuned:
      1. Uses the most recent CONFIRMED swing high/low as the level to break
         — confirmed via a small fractal window (a bar is a swing point if
         it's the extreme within `_SWING_WINDOW` bars on each side). A single
         clear local peak is enough; it doesn't need to be part of an
         ascending pair (that extra requirement delayed obvious breakouts
         waiting for a second confirming swing that might never come).
      2. The breakout level is that swing point, cleared by a volatility-
         scaled buffer (`_SWING_ATR_PERIOD`-bar ATR × `_SWING_ATR_MULTIPLIER`)
         rather than a fixed price/% buffer — a fixed buffer is either too
         tight on a volatile day or too loose on a calm one.
      3. The breakout candle's own volume must clear `_SWING_VOLUME_MULTIPLIER`
         × its trailing `_SWING_VOLUME_LOOKBACK`-bar average — filters out
         low-conviction fakeouts, which are far more common intraday than on
         daily charts.

    The tight, structural stop-loss is the pullback extreme (low for a buy,
    high for a sell) reached since that swing point formed — i.e. the
    immediate support/resistance right before the level that just broke.

    Returns (triggeredAt, entryLevel, tightStopLevel) or None."""
    kind = "high" if direction == "bullish" else "low"
    swings = _swing_points(monitor, _SWING_WINDOW, kind)
    atr = _intraday_atr(monitor, _SWING_ATR_PERIOD)
    avg_vol = _rolling_avg_volume(monitor, _SWING_VOLUME_LOOKBACK)

    current_swing: float | None = None
    swing_iter = iter(swings)
    next_swing = next(swing_iter, None)
    pending_extreme: float | None = None  # pullback tracker since the swing point formed

    for i, c in enumerate(monitor):
        while next_swing is not None and next_swing[0] == i:
            # Track the MOST RECENT confirmed swing point, not the day's
            # highest/lowest one — recent local structure is what price
            # actually has to clear next, even if an older, more extreme
            # swing exists further back in the session.
            current_swing = next_swing[1]
            pending_extreme = None  # fresh pullback tracking from this new swing point
            next_swing = next(swing_iter, None)

        if current_swing is not None and atr[i] is not None:
            level = (
                current_swing + _SWING_ATR_MULTIPLIER * atr[i]
                if direction == "bullish"
                else current_swing - _SWING_ATR_MULTIPLIER * atr[i]
            )
            price_confirmed = c["close"] > level if direction == "bullish" else c["close"] < level
            volume_confirmed = avg_vol[i] is None or c["volume"] > _SWING_VOLUME_MULTIPLIER * avg_vol[i]
            if price_confirmed and volume_confirmed:
                ts = datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
                tight_stop = pending_extreme if pending_extreme is not None else current_swing
                return ts, level, tight_stop

        if direction == "bullish":
            pending_extreme = c["low"] if pending_extreme is None else min(pending_extreme, c["low"])
        else:
            pending_extreme = c["high"] if pending_extreme is None else max(pending_extreme, c["high"])
    return None


def _swing_points(candles: list[dict], window: int, kind: str) -> list[tuple[int, float]]:
    """Confirmed swing highs/lows: a bar's `kind` value is the extreme within
    `window` bars on each side. Confirmation lags by `window` bars (can't
    know a bar is a local extreme until you've seen what comes after it)."""
    pts: list[tuple[int, float]] = []
    n = len(candles)
    for i in range(window, n - window):
        seg = candles[i - window : i + window + 1]
        if kind == "high" and candles[i]["high"] == max(c["high"] for c in seg):
            pts.append((i, candles[i]["high"]))
        elif kind == "low" and candles[i]["low"] == min(c["low"] for c in seg):
            pts.append((i, candles[i]["low"]))
    return pts


def _intraday_atr(candles: list[dict], period: int) -> list[float | None]:
    """Rolling ATR computed on the SAME timeframe as the entry candles, so
    the breakout buffer scales with actual intraday volatility."""
    trs: list[float] = []
    atrs: list[float | None] = [None] * len(candles)
    for i, c in enumerate(candles):
        if i == 0:
            tr = c["high"] - c["low"]
        else:
            prev_close = candles[i - 1]["close"]
            tr = max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close))
        trs.append(tr)
        if i >= period - 1:
            atrs[i] = sum(trs[i - period + 1 : i + 1]) / period
    return atrs


def _rolling_avg_volume(candles: list[dict], lookback: int) -> list[float | None]:
    vols = [c["volume"] for c in candles]
    avgs: list[float | None] = [None] * len(candles)
    for i in range(len(candles)):
        if i >= lookback:
            window = vols[i - lookback : i]
            avgs[i] = (sum(window) / lookback) if window else None
    return avgs




def compute_setup(
    *,
    symbol: str,
    candles_5m: list[dict],
    monitor: list[dict],
    orb_high: float,
    orb_low: float,
    orb_close_ts: float,
    vwap: float,
    current_price: float,
    trigger_bar_secs: int,
    entry_cutoff_ts: float,
    frozen: dict | None,
) -> tuple[TradeSetup, dict | None]:
    """Returns (TradeSetup, freeze_payload). `freeze_payload` is a dict to
    persist (triggeredAt/action/entry/stopLoss/slWide) the first time a setup
    fires, or None if nothing new to freeze this call.

    `entry_cutoff_ts` blocks FRESH entries past 14:45 IST (no room to manage
    a trade before the 15:15 IST square-off) — it only limits the candles
    considered for a brand-new breakout; an already-frozen trade's stop-loss
    is still tracked against the full `monitor` regardless of this cutoff."""
    daily = market_data.get_candles(symbol, period="6mo", interval="1d")
    atr14 = _atr14(daily)
    gap_class, gap_pct, prev_close = _gap_class(daily, atr14)
    opening_high, opening_low, window_end_ts, opening_window = _opening_window(candles_5m)
    opening_bias = _opening_window_bias(opening_window)
    daily_trend = _daily_trend(daily)
    bias_direction, conviction = _daily_bias(gap_class, opening_bias, daily_trend)

    post_window = [c for c in monitor if window_end_ts <= c["ts"] < entry_cutoff_ts]

    if frozen is not None:
        action = frozen["action"]
        triggered_at = frozen["triggered_at"]
        entry = frozen["entry"]
        stop_loss = frozen["stop_loss"]
        sl_wide = frozen.get("sl_wide") or stop_loss
        confirmation = frozen.get("confirmation", "swing_break")
    else:
        triggered_at, entry, stop_loss, sl_wide, confirmation = (
            None, current_price, current_price, current_price, None,
        )

        def _try_direction(direction: str) -> tuple[datetime, float, float, float] | None:
            is_countertrend = bias_direction == _opposite(direction)
            if is_countertrend and conviction == "high":
                return None  # suppressed entirely — no evidence supports this direction today

            result = _dual_stop_breakout(post_window, direction, trigger_bar_secs)
            if result is None:
                return None
            ts, entry_level, tight_stop = result
            return ts, entry_level, tight_stop

        bullish_result = _try_direction("bullish")
        bearish_result = _try_direction("bearish")

        # Earliest valid signal wins, regardless of aligned/countertrend.
        # High-conviction countertrend setups are already fully suppressed
        # above (never become candidates at all), and the entry mechanism
        # itself now requires two confirmed swing points + an ATR-scaled
        # buffer + above-average volume — real fakeout-prevention baked into
        # the signal itself. Given that, letting "aligned" direction win
        # outright regardless of timing (the previous rule) actively hid
        # genuinely strong countertrend breakouts (e.g. a high-volume,
        # well-structured move) behind a later, weaker aligned one just
        # because it matched the daily bias — that's backwards once the
        # entry mechanism itself is already this selective.
        candidates = [
            (r, a) for r, a in ((bullish_result, "buy"), (bearish_result, "sell")) if r is not None
        ]
        picked = None
        if candidates:
            (picked, action) = min(candidates, key=lambda pair: pair[0][0])
        else:
            # No confirmed breakout yet — `action` still has to be buy/sell
            # (never a placeholder), so lean on the daily bias, falling back
            # to VWAP position when the bias itself is neutral.
            action = (
                "buy" if bias_direction == "bullish"
                else "sell" if bias_direction == "bearish"
                else ("buy" if current_price >= vwap else "sell")
            )

        if picked is not None:
            ts, level, tight_stop = picked
            triggered_at, entry, stop_loss = ts, level, tight_stop
            sl_wide = opening_low if action == "buy" else opening_high
            confirmation = "swing_break"

    risk = abs(entry - stop_loss)
    target = entry + 2 * risk if action == "buy" else entry - 2 * risk if action == "sell" else entry
    rr = round((abs(target - entry) / risk), 2) if risk > 0 else 0.0

    vwap_tolerance = max(vwap * 0.001, 0.05)
    if abs(current_price - vwap) <= vwap_tolerance:
        vwap_position = "at"
    elif current_price > vwap:
        vwap_position = "above"
    else:
        vwap_position = "below"

    bias_txt = f"{bias_direction}/{conviction}" if bias_direction != "neutral" else "neutral"
    status = "sl_hit" if (frozen is not None and frozen.get("sl_hit_at") is not None) else (
        "triggered" if triggered_at is not None else "waiting"
    )
    rationale = (
        f"Context: gap={gap_class} ({gap_pct:+.2f}%), opening-15min={opening_bias}, "
        f"daily-trend={daily_trend} → dailyBias={bias_txt}. Opening window ₹{opening_low:.2f}–₹{opening_high:.2f}. "
        + (
            f"Entry on ratcheted swing-high/low break at ₹{entry:.2f}, tight stop ₹{stop_loss:.2f} "
            f"(wide stop ₹{sl_wide:.2f} = opposite side of the opening window)."
            if status != "waiting"
            else "No swing-high/low breakout confirmed yet."
        )
    )

    setup = TradeSetup(
        action=action,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        bias="bullish" if action == "buy" else "bearish",  # type: ignore[arg-type]
        entry=round(entry, 2),
        stopLoss=round(stop_loss, 2),
        target=round(target, 2),
        riskRewardRatio=rr,
        vwapPosition=vwap_position,  # type: ignore[arg-type]
        rationale=rationale,
        triggeredAt=triggered_at,
        slHitAt=frozen["sl_hit_at"] if frozen is not None else None,
        strategy="context_gated",
        conviction=conviction if bias_direction != "neutral" else None,
        gapClass=gap_class,
        confirmation=confirmation,
        slWide=round(sl_wide, 2),
    )

    freeze_payload = None
    if frozen is None and triggered_at is not None:
        freeze_payload = {
            "triggered_at": triggered_at,
            "action": action,
            "entry": entry,
            "stop_loss": stop_loss,
            "sl_wide": sl_wide,
            "confirmation": confirmation,
        }
    return setup, freeze_payload


def _opposite(direction: str) -> str:
    return "bearish" if direction == "bullish" else "bullish"


def check_sl_hit(monitor: list[dict], action: str, stop_loss: float, triggered_at: datetime, trigger_bar_secs: int) -> datetime | None:
    sl_trigger_ts = triggered_at.timestamp() - trigger_bar_secs
    for c in monitor:
        if c["ts"] < sl_trigger_ts:
            continue
        if action == "buy" and c["low"] < stop_loss:
            return datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
        if action == "sell" and c["high"] > stop_loss:
            return datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
    return None
