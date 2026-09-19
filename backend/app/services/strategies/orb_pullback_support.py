"""ORB + Pullback Support strategy — enters early at the bottom of the pullback
as soon as the first supporting GREEN candle forms and its level is confirmed.

Design:
  1. Breakout: 15-minute ORB swing high/low box (9:15-9:30 IST).
     First 3-min candle after 9:30 IST closing beyond the box confirms the breakout.
  2. Pullback: wait for >= 1 opposite-colour candle (red for BUY, green for SELL).
     Collect the pullback candles and track the extreme (lowest low for BUY,
     highest high for SELL).
  3. Supporting Candle — always the first GREEN candle seen:
       BUY:  First GREEN candle after the red pullback.
             Supporting level = its HIGH.
       SELL: First GREEN candle of the pullback (bouncing against the downtrend).
             Supporting level = its LOW.
  4. Entry:
       BUY:  Next candle closes ABOVE supporting GREEN candle HIGH (close mode)
             OR LTP / candle High > high (touch mode).
       SELL: A RED candle closes BELOW supporting GREEN candle LOW (close mode)
             OR any candle Low < low (touch mode).
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


def _find_support_entry(
    monitor: list[dict], breakout_idx: int, direction: str, entry_cutoff_ts: float, entry_mode: str = "close",
) -> tuple[float, float, int, datetime | None] | None:
    """Scans for the pullback and candidate supporting candles in the breakout direction.

    BUY:  Pullback = red candles.  Supporting candle = first GREEN recovery candle.
          Trigger level = GREEN candle HIGH.
          Entry: any candle CLOSES above that HIGH (close mode)
                 or any candle HIGH breaks it (touch mode).

    SELL: Pullback = green candles.  Supporting candle = first GREEN pullback candle.
          Trigger level = GREEN candle LOW.
          Entry: a RED candle CLOSES below that LOW (close mode)
                 or any candle LOW breaks it (touch mode).
          If more green candles form, the stop is extended to their highs and the
          trigger is lowered to their lows (use the tightest / lowest green low seen).

    When entry_mode == 'close':
      BUY  — any candle close above GREEN high.
      SELL — only a RED candle close below GREEN low.
    When entry_mode == 'touch':
      Triggers as soon as a candle extreme (High for BUY, Low for SELL) breaks the level.

    Returns:
      (support_trigger_level, tight_stop, support_candle_idx, triggered_at)
      where triggered_at is datetime if already broken historically, else None (candidate waiting for break).
      Returns None if no candidate supporting candle has formed yet.
    """
    pullback_count = 0
    pullback_extreme: float | None = None
    candidate: tuple[float, float, int] | None = None

    for i in range(breakout_idx + 1, len(monitor)):
        c = monitor[i]
        if c["ts"] >= entry_cutoff_ts:
            break
        is_red = c["close"] < c["open"]
        is_green = c["close"] > c["open"]

        if direction == "buy":
            if candidate is not None:
                trig_lvl, t_stop, cand_idx = candidate
                # Check if this bar triggered entry
                triggered = c["close"] > trig_lvl if entry_mode == "close" else c["high"] > trig_lvl
                if triggered:
                    triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                    return trig_lvl, t_stop, cand_idx, triggered_at
                # Did this bar resume the pullback (red candle or lower low)?
                if c["low"] < t_stop or is_red:
                    candidate = None
                    pullback_count += 1
                    pullback_extreme = min(t_stop, c["low"])
                elif is_green:
                    # Keep first supporting candle's trigger level; track lowest support low
                    candidate = (trig_lvl, min(t_stop, c["low"]), cand_idx)
            else:
                if is_red:
                    pullback_count += 1
                    pullback_extreme = c["low"] if pullback_extreme is None else min(pullback_extreme, c["low"])
                elif is_green and pullback_count >= _MIN_PULLBACK_CANDLES:
                    candidate = (c["high"], min(pullback_extreme, c["low"]), i)
        else:  # sell — supporting candle = first GREEN pullback candle; trigger = its LOW
            if candidate is not None:
                trig_lvl, t_stop, cand_idx = candidate
                # Check if this bar triggered entry:
                #   close mode  → a RED candle must close below the supporting green candle's LOW
                #   touch mode  → any candle whose low dips below the trigger level
                if entry_mode == "close":
                    triggered = is_red and c["close"] < trig_lvl
                else:
                    triggered = c["low"] < trig_lvl
                if triggered:
                    triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                    return trig_lvl, t_stop, cand_idx, triggered_at
                # More GREEN candles: pullback extending higher — widen stop, lower trigger
                if is_green:
                    candidate = (min(trig_lvl, c["low"]), max(t_stop, c["high"]), cand_idx)
                # RED candle that didn't trigger — keep candidate alive
            else:
                if is_green:
                    # First GREEN candle after SELL breakout = supporting candle
                    pullback_extreme = c["high"] if pullback_extreme is None else max(pullback_extreme, c["high"])
                    candidate = (c["low"], pullback_extreme, i)

    if candidate is not None:
        trig_lvl, t_stop, cand_idx = candidate
        return trig_lvl, t_stop, cand_idx, None

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
    entry_mode: str = "close",
) -> tuple[TradeSetup, dict | None]:
    orb_macro_sl_buy = orb_low
    orb_macro_sl_sell = orb_high
    gap_bias = _gap_bias(candles_5m)

    if frozen is not None:
        action = frozen["action"]
        triggered_at = frozen["triggered_at"]
        entry = frozen["entry"]  # Breakout price
        stop_loss = frozen["stop_loss"]
        trigger_price = frozen.get("trigger_price")  # Actual fill price
        sl_wide = frozen.get("sl_wide") or (orb_low if action == "buy" else orb_high)
        status = "triggered"
        _main_sl_note = f" · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})" if sl_wide else ""
        fill_level = trigger_price if trigger_price is not None else entry
        rationale = (
            f"Broke ORB at ₹{entry:.2f}, pulled back, and entered at support candle level ₹{fill_level:.2f}.{_main_sl_note}"
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

            support_res = _find_support_entry(monitor, breakout_idx, action, entry_cutoff_ts, entry_mode=entry_mode)
            if support_res is None:
                triggered_at, trigger_price = None, None
                entry = orb_break_price
                stop_loss = sl_wide
                status = "pending_entry"
                rationale = (
                    f"Broke {'above' if action == 'buy' else 'below'} the opening range at ₹{orb_break_price:.2f}. "
                    f"Watching for pullback and first supporting green candle."
                )
            else:
                support_trigger_level, tight_stop, support_idx, hist_triggered_at = support_res

                if hist_triggered_at is not None:
                    triggered_at = hist_triggered_at
                    trigger_price = support_trigger_level
                    entry = orb_break_price
                    stop_loss = tight_stop
                    status = "triggered"
                    if action == "buy":
                        mode_desc = "closed above" if entry_mode == "close" else "broke above"
                        ref_desc = "green supporting candle high"
                    else:
                        mode_desc = "red candle closed below" if entry_mode == "close" else "broke below"
                        ref_desc = "green supporting candle low"
                    rationale = (
                        f"Broke ORB at ₹{orb_break_price:.2f}, pulled back, and {mode_desc} "
                        f"{ref_desc} ₹{support_trigger_level:.2f}. "
                        f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                    )
                else:
                    # In 'touch' mode, check live LTP against the candidate support candle
                    if entry_mode == "touch":
                        ltp_crossed = (
                            (action == "buy" and current_price > support_trigger_level) or
                            (action == "sell" and current_price < support_trigger_level)
                        )
                        if ltp_crossed:
                            triggered_at = datetime.now(tz=timezone.utc)
                            trigger_price = support_trigger_level
                            entry = orb_break_price
                            stop_loss = tight_stop
                            status = "triggered"
                            rationale = (
                                f"Broke ORB at ₹{orb_break_price:.2f}, pulled back, and LTP "
                                f"{'broke above' if action == 'buy' else 'broke below'} the green supporting candle "
                                f"{'high' if action == 'buy' else 'low'} ₹{support_trigger_level:.2f}. "
                                f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                            )
                        else:
                            triggered_at, trigger_price = None, support_trigger_level
                            entry = orb_break_price
                            stop_loss = tight_stop
                            status = "pending_entry"
                            rationale = (
                                f"Broke {'above' if action == 'buy' else 'below'} ORB at ₹{orb_break_price:.2f}. "
                                f"Green supporting candle formed — waiting for LTP to "
                                f"{'cross above' if action == 'buy' else 'break below'} ₹{support_trigger_level:.2f}."
                            )
                    else:
                        # In 'close' mode, wait for the 3m candle to close
                        triggered_at, trigger_price = None, support_trigger_level
                        entry = orb_break_price
                        stop_loss = tight_stop
                        status = "pending_entry"
                        if action == "buy":
                            rationale = (
                                f"Broke above ORB at ₹{orb_break_price:.2f}. "
                                f"Green supporting candle formed — waiting for 3m candle to close above ₹{support_trigger_level:.2f}."
                            )
                        else:
                            rationale = (
                                f"Broke below ORB at ₹{orb_break_price:.2f}. "
                                f"Green supporting candle formed — waiting for red 3m candle to close below ₹{support_trigger_level:.2f}."
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
        entryMode=entry_mode,  # type: ignore[arg-type]
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
            "entry_mode": entry_mode,
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
