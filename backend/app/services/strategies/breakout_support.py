"""Breakout Support strategy (`breakout_support`).

Engineered with Dynamic Setup Reversal:
  1. Breakout: 15-minute ORB swing high/low box (9:15-9:30 IST).
     The first candle (9:15) is ALWAYS included in the opening range calculation.
     A 3-minute candle closing beyond the ORB box establishes the initial breakout.
  2. Dynamic Reversal:
     If the market reverses and a 3-minute candle CLOSES beyond the opposite ORB level
     (e.g., initially broke Low for SELL, but later closes above ORB High):
     - The setup dynamically flips direction (SELL -> BUY or BUY -> SELL).
     - Breakout level (BO), Entry, Tight SL, and Macro Stop Loss (MSL) are all recalculated.
     - Pullback and supporting candle scanning restarts from the reversal candle index.
  3. Pullback: wait for >= 1 opposite-colour candle (red for BUY, green for SELL).
     Tracks the pullback extreme (lowest low for BUY, highest high for SELL).
  4. Supporting Candle:
     BUY:  First GREEN candle after red pullback. Supporting level = its HIGH.
     SELL: First RED candle after green pullback. Supporting level = its LOW.
  5. Entry Trigger:
     - 3-Min Candle mode (close): Next candle closes beyond supporting candle level.
     - Latest Price mode (touch): Candle high/low or live LTP breaches supporting candle level.
  6. Stop Losses:
     - Tight Stop: Pullback extreme with user-configured SL buffer %.
     - Macro Stop (MSL): Opposite ORB boundary (ORB Low for BUY, ORB High for SELL).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from zoneinfo import ZoneInfo

from app.schemas.stock import TradeSetup

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_GAP_BIAS_MIN_CANDLES = 6
_GAP_BIAS_MIN_MOVE_PCT = 0.5
_GAP_BIAS_BODY_FRACTION = 0.5
_GAP_BIAS_CLOSE_POSITION = 0.6
_MIN_PULLBACK_CANDLES = 1


def _apply_sl_buffer(
    action: str,
    tight_stop: float,
    entry_price: float | None = None,
    sl_buffer_pct: float = 25.0,
) -> float:
    """Apply the user's configured SL buffer percentage to the tight stop-loss.

    Formula adheres strictly to User Settings:
      Risk = abs(Entry - Tight SL)
      Buffer Amount = Risk * (sl_buffer_pct / 100.0)
      BUY:  Tight SL - Buffer Amount (widens stop below support low)
      SELL: Tight SL + Buffer Amount (widens stop above support high)
    """
    if entry_price is not None and entry_price > 0:
        raw_risk = abs(entry_price - tight_stop)
        buffer_amt = raw_risk * (sl_buffer_pct / 100.0)
    else:
        buffer_amt = tight_stop * (sl_buffer_pct / 10000.0)

    if action == "buy":
        return round(tight_stop - buffer_amt, 2)
    return round(tight_stop + buffer_amt, 2)


def _gap_bias(candles_5m: list[dict]) -> str | None:
    """Detects strong directional impulse on the opening candle."""
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


def _find_dynamic_breakout(
    monitor: list[dict],
    orb_high: float,
    orb_low: float,
    orb_close_ts: float,
    entry_cutoff_ts: float,
    gap_bias: str | None = None,
) -> tuple[int, str, bool] | None:
    """Chronologically tracks breakouts and dynamic reversals.

    Scans candles after orb_close_ts (9:30/9:35 IST):
      - Determines initial breakout (candle close > orb_high or < orb_low).
      - If price subsequently closes beyond opposite ORB level, flips direction.

    Returns:
      (latest_breakout_candle_idx, direction ['buy'|'sell'], has_reversed [bool])
      or None if no breakout occurred.
    """
    active_breakout: tuple[int, str] | None = None
    has_reversed = False

    for i, c in enumerate(monitor):
        if c["ts"] < orb_close_ts or c["ts"] >= entry_cutoff_ts:
            continue

        c_close = c["close"]

        if active_breakout is None:
            # Initial breakout check
            broke_high = c_close > orb_high
            broke_low = c_close < orb_low

            if broke_high and broke_low:
                # Extreme volatility bar: use candle close relative to open
                direction = "buy" if c_close >= c["open"] else "sell"
                active_breakout = (i, direction)
            elif broke_high:
                active_breakout = (i, "buy")
            elif broke_low:
                active_breakout = (i, "sell")
        else:
            current_dir = active_breakout[1]
            if current_dir == "buy" and c_close < orb_low:
                # Dynamic Reversal: 3m candle closed below ORB Low
                active_breakout = (i, "sell")
                has_reversed = True
            elif current_dir == "sell" and c_close > orb_high:
                # Dynamic Reversal: 3m candle closed above ORB High
                active_breakout = (i, "buy")
                has_reversed = True

    if active_breakout is None:
        return None
    return active_breakout[0], active_breakout[1], has_reversed


def _find_support_entry(
    monitor: list[dict],
    breakout_idx: int,
    direction: str,
    entry_cutoff_ts: float,
    entry_mode: str = "close",
) -> tuple[float | None, float | None, int | None, datetime | None, int, str, str, str]:
    """Scans for pullback and support candle starting from breakout_idx + 1.

    BUY:  Pullback = red candles. Supporting candle = first GREEN recovery candle.
          Trigger level = GREEN candle HIGH.
    SELL: Pullback = green candles. Supporting candle = first RED rejection candle.
          Trigger level = RED candle LOW.

    Returns:
      (support_trigger_level, tight_stop, support_candle_idx, triggered_at,
       stage, stage_key, stage_label, stage_desc)
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
                triggered = c["close"] > trig_lvl if entry_mode == "close" else c["high"] > trig_lvl
                if triggered:
                    triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                    return (
                        trig_lvl, t_stop, cand_idx, triggered_at,
                        5, "triggered", "Entered",
                        f"Entered at ₹{trig_lvl:.2f}. Stop ₹{t_stop:.2f}.",
                    )
                # Resumed pullback?
                if c["low"] < t_stop or is_red:
                    candidate = None
                    pullback_count += 1
                    pullback_extreme = min(t_stop, c["low"])
                elif is_green:
                    candidate = (trig_lvl, min(t_stop, c["low"]), cand_idx)
            else:
                if is_red:
                    pullback_count += 1
                    pullback_extreme = c["low"] if pullback_extreme is None else min(pullback_extreme, c["low"])
                elif is_green and pullback_count >= _MIN_PULLBACK_CANDLES:
                    candidate = (c["high"], min(pullback_extreme, c["low"]), i)

        else:  # sell
            if candidate is not None:
                trig_lvl, t_stop, cand_idx = candidate
                triggered = c["close"] < trig_lvl if entry_mode == "close" else c["low"] < trig_lvl
                if triggered:
                    triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                    return (
                        trig_lvl, t_stop, cand_idx, triggered_at,
                        5, "triggered", "Entered",
                        f"Entered at ₹{trig_lvl:.2f}. Stop ₹{t_stop:.2f}.",
                    )
                # Resumed bounce/pullback?
                if c["high"] > t_stop or is_green:
                    candidate = None
                    pullback_count += 1
                    pullback_extreme = max(t_stop, c["high"])
                elif is_red:
                    candidate = (trig_lvl, max(t_stop, c["high"]), cand_idx)
            else:
                if is_green:
                    pullback_count += 1
                    pullback_extreme = c["high"] if pullback_extreme is None else max(pullback_extreme, c["high"])
                elif is_red and pullback_count >= _MIN_PULLBACK_CANDLES:
                    candidate = (c["low"], max(pullback_extreme, c["high"]), i)

    if candidate is not None:
        trig_lvl, t_stop, cand_idx = candidate
        c_desc = f"{'Green' if direction == 'buy' else 'Red'} support candle formed at ₹{trig_lvl:.2f}. Watching for price break."
        return (
            trig_lvl, t_stop, cand_idx, None,
            4, "support_formed", "Support Formed", c_desc,
        )

    if pullback_count >= 1:
        p_ext_str = f"₹{pullback_extreme:.2f}" if pullback_extreme is not None else ""
        p_desc = f"Pullback active ({pullback_count} bar{'s' if pullback_count > 1 else ''}, extreme {p_ext_str}). Waiting for support candle."
        return (
            None, pullback_extreme, None, None,
            3, "pb_forming", "Wait Support", p_desc,
        )

    return (
        None, None, None, None,
        2, "bo_wait_pb", "BO · Wait PB", "Breakout confirmed. Waiting for pullback to start.",
    )


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
    setup_trend: str = "flat",
    gap_bias: str | None = None,
    sl_buffer_pct: float = 25.0,
) -> tuple[TradeSetup, dict | None]:
    """Computes the Breakout Support trade setup with dynamic reversal tracking."""
    if gap_bias is None:
        gap_bias = _gap_bias(candles_5m)

    # 1. Detect dynamic breakout and active regime
    breakout_info = _find_dynamic_breakout(
        monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts, gap_bias=gap_bias,
    )

    # Handle frozen state: if market reversed opposite to frozen trade, discard frozen state
    active_frozen = frozen
    if frozen is not None and breakout_info is not None:
        _, active_direction, _ = breakout_info
        if frozen["action"] != active_direction:
            # Reversal occurred! Discard stale opposite frozen state so setup flips cleanly
            active_frozen = None

    if active_frozen is not None:
        action = active_frozen["action"]
        triggered_at = active_frozen["triggered_at"]
        entry = active_frozen["entry"]
        stop_loss = active_frozen["stop_loss"]
        trigger_price = active_frozen.get("trigger_price")
        sl_wide = active_frozen.get("sl_wide") or (orb_low if action == "buy" else orb_high)

        # Self-healing tight stop recovery if identical to sl_wide
        if abs(stop_loss - sl_wide) < 0.05 and breakout_info is not None:
            breakout_idx, _, _ = breakout_info
            support_res = _find_support_entry(monitor, breakout_idx, action, entry_cutoff_ts, entry_mode=entry_mode)
            if support_res is not None:
                _, tight_stop, _, _, _, _, _, _ = support_res
                if tight_stop is not None:
                    stop_loss = tight_stop

        status = "triggered"
        stage = 5
        stage_key = "triggered"
        stage_label = "Entered"
        fill_level = trigger_price if trigger_price is not None else entry
        stage_desc = f"Entered at support level ₹{fill_level:.2f}. Stop ₹{stop_loss:.2f}."
        rationale = (
            f"Broke ORB at ₹{entry:.2f}, pulled back, and entered at support candle level ₹{fill_level:.2f}. "
            f"Stop ₹{stop_loss:.2f}."
        )
    elif breakout_info is None:
        action = gap_bias if gap_bias is not None else ("buy" if current_price >= vwap else "sell")
        entry = orb_high if action == "buy" else orb_low
        stop_loss = orb_low if action == "buy" else orb_high
        sl_wide = stop_loss
        triggered_at, trigger_price = None, None
        status = "waiting"
        stage = 1
        stage_key = "wait_orb"
        stage_label = "Wait BO"
        stage_desc = f"Price inside opening range ₹{orb_low:.2f}–₹{orb_high:.2f}. Waiting for a decisive break."
        rationale = stage_desc
    else:
        breakout_idx, action, has_reversed = breakout_info
        orb_level = orb_high if action == "buy" else orb_low
        sl_wide = orb_low if action == "buy" else orb_high

        support_res = _find_support_entry(monitor, breakout_idx, action, entry_cutoff_ts, entry_mode=entry_mode)
        support_trigger_level, tight_stop, support_idx, hist_triggered_at, stage, stage_key, stage_label, stage_desc = support_res

        reversal_prefix = "Reversed: " if has_reversed else ""

        if stage in (2, 3):
            triggered_at, trigger_price = None, None
            entry = orb_level
            status = "pending_entry"
            stop_loss = sl_wide
            rationale = f"{reversal_prefix}{stage_desc}"
            if has_reversed:
                stage_desc = f"{reversal_prefix}{stage_desc}"
        elif stage == 4:
            entry = orb_level
            ref_entry = support_trigger_level or entry
            stop_loss = (
                _apply_sl_buffer(action, tight_stop, ref_entry, sl_buffer_pct)
                if tight_stop is not None
                else sl_wide
            )
            assert support_trigger_level is not None
            if entry_mode == "touch":
                ltp_crossed = (
                    (action == "buy" and current_price > support_trigger_level) or
                    (action == "sell" and current_price < support_trigger_level)
                )
                if ltp_crossed:
                    triggered_at = datetime.now(tz=timezone.utc)
                    trigger_price = support_trigger_level
                    status = "triggered"
                    stage = 5
                    stage_key = "triggered"
                    stage_label = "Entered"
                    ref_desc = "green supporting candle high" if action == "buy" else "red supporting candle low"
                    action_word = "broke above" if action == "buy" else "broke below"
                    stage_desc = f"Entered: LTP {action_word} {ref_desc} ₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."
                    rationale = f"{reversal_prefix}Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, pulled back to ₹{stop_loss:.2f}, and LTP {action_word} {ref_desc} ₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."
                else:
                    triggered_at, trigger_price = None, support_trigger_level
                    status = "pending_entry"
                    ref_desc = "Green" if action == "buy" else "Red"
                    action_word = "cross above" if action == "buy" else "break below"
                    stage_desc = f"{reversal_prefix}{ref_desc} support candle formed at ₹{support_trigger_level:.2f}. Waiting for LTP to {action_word}."
                    rationale = f"{reversal_prefix}Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. {ref_desc} supporting candle formed — waiting for LTP to {action_word} ₹{support_trigger_level:.2f}."
            else:
                triggered_at, trigger_price = None, support_trigger_level
                status = "pending_entry"
                ref_desc = "Green" if action == "buy" else "Red"
                action_word = "close above" if action == "buy" else "close below"
                stage_desc = f"{reversal_prefix}{ref_desc} support candle formed at ₹{support_trigger_level:.2f}. Waiting for 3m candle to {action_word}."
                rationale = f"{reversal_prefix}Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. {ref_desc} supporting candle formed — waiting for 3m candle to {action_word} ₹{support_trigger_level:.2f}."
        elif stage == 5:
            triggered_at = hist_triggered_at
            trigger_price = support_trigger_level
            entry = orb_level
            ref_entry = support_trigger_level or entry
            stop_loss = (
                _apply_sl_buffer(action, tight_stop, ref_entry, sl_buffer_pct)
                if tight_stop is not None
                else sl_wide
            )
            status = "triggered"
            mode_desc = "closed above" if entry_mode == "close" else "broke above"
            ref_desc = "green supporting candle high" if action == "buy" else "red supporting candle low"
            if action == "sell":
                mode_desc = "closed below" if entry_mode == "close" else "broke below"
            stage_desc = f"Entered at ₹{trigger_price:.2f}. Stop ₹{stop_loss:.2f}."
            rationale = f"{reversal_prefix}Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, pulled back to ₹{stop_loss:.2f}, and {mode_desc} {ref_desc} ₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."

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
        strategy="breakout_support",
        conviction=None,
        gapClass="up" if gap_bias == "buy" else "down" if gap_bias == "sell" else None,
        confirmation="breakout_support" if status == "triggered" else None,
        slWide=round(sl_wide, 2) if sl_wide is not None else None,
        tightStop=round(tight_stop, 2) if ('tight_stop' in locals() and tight_stop is not None) else None,
        triggerPrice=round(trigger_price, 2) if trigger_price is not None else None,
        entryMode=entry_mode,  # type: ignore[arg-type]
        stage=stage,
        stageKey=stage_key,  # type: ignore[arg-type]
        stageLabel=stage_label,
        stageDesc=stage_desc,
        includeFirstCandle=True,
    )

    freeze_payload = None
    if status == "triggered":
        freeze_payload = {
            "triggered_at": triggered_at,
            "action": action,
            "entry": entry,
            "stop_loss": stop_loss,
            "tight_stop": tight_stop if ('tight_stop' in locals() and tight_stop is not None) else None,
            "trigger_price": trigger_price,
            "sl_wide": sl_wide,
            "entry_mode": entry_mode,
            "include_first_candle": True,
        }
    return setup, freeze_payload


def check_sl_hit(
    monitor: list[dict],
    action: str,
    stop_loss: float,
    triggered_at: datetime,
    trigger_bar_secs: int,
    entry_mode: str = "close",
    current_price: float | None = None,
) -> datetime | None:
    """Checks if Stop Loss was breached by monitor candles or current price."""
    trig_ts = triggered_at.timestamp()
    for c in monitor:
        if entry_mode == "close":
            if c["ts"] <= trig_ts:
                continue
        else:
            if c["ts"] < trig_ts:
                continue
        if action == "buy" and c["low"] < stop_loss:
            return datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)
        if action == "sell" and c["high"] > stop_loss:
            return datetime.fromtimestamp(c["ts"] + trigger_bar_secs, tz=timezone.utc)

    # Also check current live price (LTP)
    if current_price is not None and current_price > 0:
        if action == "buy" and current_price < stop_loss:
            return datetime.now(tz=timezone.utc)
        if action == "sell" and current_price > stop_loss:
            return datetime.now(tz=timezone.utc)

    return None
