"""ORB + Pullback Support strategy — enters early at the bottom of the pullback
as soon as the first supporting candle in the breakout direction forms and its
extreme is broken, without waiting for the entire prior breakout peak to break.

Design:
  1. Breakout: same ORB swing high/low box as `orb_vwap` / `orb_pullback`.
     First 3-min candle after 9:35 IST closing beyond the box confirms the breakout.
  2. Pullback: wait for >= 1 opposite-colour candle (red for BUY, green for SELL).
     Collect the pullback candles and track the extreme (lowest low for BUY,
     highest high for SELL).
  3. First Supporting Candle:
     The first candle back in the breakout direction that completes after the pullback:
       - BUY:  First GREEN candle (`close > open`). Supporting level = its HIGH.
       - SELL: First RED candle (`close < open`).   Supporting level = its LOW.
  4. Entry:
     Triggers when LTP or subsequent candle breaks the supporting candle's level:
       - BUY:  LTP or candle High > `support_candle.high` -> fill at `support_candle.high`.
       - SELL: LTP or candle Low  < `support_candle.low`  -> fill at `support_candle.low`.
  5. Stop Losses:
     - Tight Stop: The extreme of the pullback (lowest low for BUY, highest high for SELL).
     - Macro Stop: The structural ORB level (ORB Low for BUY, ORB High for SELL).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.stock import TradeSetup

_GAP_BIAS_MIN_CANDLES = 6
_GAP_BIAS_MIN_MOVE_PCT = 0.5
_GAP_BIAS_BODY_FRACTION = 0.5
_GAP_BIAS_CLOSE_POSITION = 0.6
_MIN_PULLBACK_CANDLES = 1


def _gap_bias(candles_5m: list[dict]) -> str | None:
    """Same gap-bias override rule as orb_vwap/orb_pullback."""
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


def _find_breakout(
    monitor: list[dict], orb_high: float, orb_low: float, orb_close_ts: float,
    entry_cutoff_ts: float, gap_bias: str | None,
) -> tuple[int, str] | None:
    """First candle whose CLOSE clears the ORB box in an allowed direction."""
    allow_up = gap_bias != "sell"
    allow_down = gap_bias != "buy"
    for i, c in enumerate(monitor):
        if c["ts"] < orb_close_ts or c["ts"] >= entry_cutoff_ts:
            continue
        if allow_up and c["close"] > orb_high:
            return i, "buy"
        if allow_down and c["close"] < orb_low:
            return i, "sell"
    return None


def _find_support_candle(
    monitor: list[dict], breakout_idx: int, direction: str, entry_cutoff_ts: float,
) -> tuple[float, float, int] | None:
    """Scan for the pullback, then identify the FIRST supporting candle in the trade direction.

    Returns:
      (support_trigger_level, tight_stop, support_candle_idx)
    where:
      BUY:
        support_trigger_level = HIGH of the first green candle after pullback
        tight_stop            = lowest LOW of the pullback & support candle
      SELL:
        support_trigger_level = LOW of the first red candle after pullback
        tight_stop            = highest HIGH of the pullback & support candle
    or None if pullback or supporting candle has not yet formed.
    """
    pullback_count = 0
    pullback_extreme: float | None = None
    last_pb_idx = breakout_idx

    i = breakout_idx + 1
    while i < len(monitor):
        c = monitor[i]
        if c["ts"] >= entry_cutoff_ts:
            break
        is_red = c["close"] < c["open"]
        is_green = c["close"] > c["open"]

        if direction == "buy":
            if is_red:
                pullback_count += 1
                last_pb_idx = i
                pullback_extreme = c["low"] if pullback_extreme is None else min(pullback_extreme, c["low"])
                i += 1
            else:
                if pullback_count >= _MIN_PULLBACK_CANDLES:
                    # Red pullback completed! This first non-red / green candle is our SUPPORT candle
                    if is_green:
                        support_trigger_level = c["high"]
                        tight_stop = min(pullback_extreme, c["low"])
                        return support_trigger_level, tight_stop, i
                    # Doji: keep scanning for the supporting green candle
                    i += 1
                else:
                    # Interrupted before minimum pullback
                    pullback_count = 0
                    pullback_extreme = None
                    i += 1
        else:  # sell
            if is_green:
                pullback_count += 1
                last_pb_idx = i
                pullback_extreme = c["high"] if pullback_extreme is None else max(pullback_extreme, c["high"])
                i += 1
            else:
                if pullback_count >= _MIN_PULLBACK_CANDLES:
                    # Green pullback completed! This first red candle is our SUPPORT candle
                    if is_red:
                        support_trigger_level = c["low"]
                        tight_stop = max(pullback_extreme, c["high"])
                        return support_trigger_level, tight_stop, i
                    # Doji: keep scanning for the supporting red candle
                    i += 1
                else:
                    pullback_count = 0
                    pullback_extreme = None
                    i += 1

    return None


def _find_support_cross(
    monitor: list[dict], support_idx: int, direction: str,
    support_trigger_level: float, entry_cutoff_ts: float,
) -> tuple[datetime, float] | None:
    """Find the first candle AFTER the supporting candle whose HIGH (BUY) or LOW (SELL)
    crosses `support_trigger_level`."""
    for c in monitor[support_idx + 1:]:
        if c["ts"] >= entry_cutoff_ts:
            break
        if direction == "buy" and c["high"] > support_trigger_level:
            ts = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
            return ts, support_trigger_level
        if direction == "sell" and c["low"] < support_trigger_level:
            ts = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
            return ts, support_trigger_level
    return None


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
    orb_macro_sl_buy = orb_low
    orb_macro_sl_sell = orb_high
    gap_bias = _gap_bias(candles_5m)

    if frozen is not None:
        action = frozen["action"]
        triggered_at = frozen["triggered_at"]
        trigger_price = frozen.get("trigger_price")
        # Use trigger_price (actual entry fill) as entry; fall back to frozen["entry"]
        entry = trigger_price if trigger_price is not None else frozen["entry"]
        stop_loss = frozen["stop_loss"]
        sl_wide = frozen.get("sl_wide") or (orb_low if action == "buy" else orb_high)
        status = "triggered"
        _main_sl_note = f" · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})" if sl_wide else ""
        rationale = (
            f"Broke ORB, pulled back, and entered at first support candle level ₹{entry:.2f}.{_main_sl_note}"
            if trigger_price is not None
            else f"Support candle entry, tight stop ₹{stop_loss:.2f}."
        )
    else:
        breakout = _find_breakout(monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts, gap_bias)
        if breakout is None:
            action = gap_bias if gap_bias is not None else ("buy" if current_price >= vwap else "sell")
            entry = orb_high if action == "buy" else orb_low
            stop_loss = orb_low if action == "buy" else orb_high
            sl_wide = stop_loss
            triggered_at, trigger_price = None, None
            status = "waiting"
            rationale = "No ORB breakout yet — waiting for a decisive close beyond the opening range."
        else:
            breakout_idx, action = breakout
            orb_break_price = monitor[breakout_idx]["close"]
            sl_wide = orb_macro_sl_buy if action == "buy" else orb_macro_sl_sell

            support = _find_support_candle(monitor, breakout_idx, action, entry_cutoff_ts)
            if support is None:
                triggered_at, trigger_price = None, None
                entry = orb_break_price
                stop_loss = sl_wide
                status = "pending_entry"
                rationale = (
                    f"Broke {'above' if action == 'buy' else 'below'} the opening range at ₹{orb_break_price:.2f}. "
                    f"Watching for pullback and first supporting {'green' if action == 'buy' else 'red'} candle."
                )
            else:
                support_trigger_level, tight_stop, support_idx = support

                # Check if historical bars crossed the support candle level
                cross = _find_support_cross(
                    monitor, support_idx, action, support_trigger_level, entry_cutoff_ts,
                )

                if cross is None:
                    # Check live LTP
                    ltp_crossed = (
                        (action == "buy" and current_price > support_trigger_level) or
                        (action == "sell" and current_price < support_trigger_level)
                    )
                    if ltp_crossed:
                        triggered_at = datetime.now(tz=timezone.utc)
                        trigger_price = support_trigger_level
                        entry = support_trigger_level
                        stop_loss = tight_stop
                        status = "triggered"
                        rationale = (
                            f"Broke ORB at ₹{orb_break_price:.2f}, pulled back, and LTP broke "
                            f"the first support candle at ₹{support_trigger_level:.2f}. "
                            f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                        )
                    else:
                        triggered_at, trigger_price = None, support_trigger_level
                        entry = support_trigger_level
                        stop_loss = tight_stop
                        status = "pending_entry"
                        rationale = (
                            f"Broke {'above' if action == 'buy' else 'below'} ORB at ₹{orb_break_price:.2f}. "
                            f"First support candle formed — waiting for LTP to cross ₹{support_trigger_level:.2f}."
                        )
                else:
                    triggered_at, trigger_price = cross
                    entry = support_trigger_level
                    stop_loss = tight_stop
                    status = "triggered"
                    rationale = (
                        f"Broke ORB at ₹{orb_break_price:.2f}, pulled back, and broke "
                        f"the first support candle at ₹{support_trigger_level:.2f}. "
                        f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                    )

    if status == "triggered" and trigger_price is not None:
        calc_base = trigger_price
        risk = abs(trigger_price - stop_loss)
    else:
        calc_base = entry
        risk = abs(entry - stop_loss)
    target = calc_base + 2 * risk if action == "buy" else calc_base - 2 * risk if action == "sell" else calc_base
    rr = round((abs(target - calc_base) / risk), 2) if risk > 0 else 0.0

    vwap_tolerance = max(vwap * 0.001, 0.05)
    if abs(current_price - vwap) <= vwap_tolerance:
        vwap_position = "at"
    elif current_price > vwap:
        vwap_position = "above"
    else:
        vwap_position = "below"

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
        slHitAt=None,
        strategy="orb_pullback_support",
        conviction=None,
        gapClass="up" if gap_bias == "buy" else "down" if gap_bias == "sell" else None,
        confirmation="pullback_support" if status == "triggered" else None,
        slWide=round(sl_wide, 2) if sl_wide is not None else None,
        triggerPrice=round(trigger_price, 2) if trigger_price is not None else None,
    )

    freeze_payload = None
    if frozen is None and status == "triggered":
        freeze_payload = {
            "triggered_at": triggered_at,
            "action": action,
            "entry": entry,
            "stop_loss": stop_loss,
            "trigger_price": trigger_price,
            "sl_wide": sl_wide,
        }
    return setup, freeze_payload


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
