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

import logging
from datetime import datetime, timezone

from app.schemas.stock import TradeSetup

logger = logging.getLogger(__name__)

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
    monitor: list[dict],
    orb_high: float,
    orb_low: float,
    orb_close_ts: float,
    entry_cutoff_ts: float,
    gap_bias: str | None = None,
    entry_mode: str = "close",
) -> tuple[int, str] | None:
    """Earliest candle after 9:35 IST that breaks beyond the ORB box in an allowed direction.
    Returns (candle_index, 'buy'|'sell') or None if no breakout occurred."""
    allow_up = gap_bias != "sell"
    allow_down = gap_bias != "buy"
    for i, c in enumerate(monitor):
        if c["ts"] < orb_close_ts or c["ts"] >= entry_cutoff_ts:
            continue
        broke_high = c["close"] > orb_high if entry_mode == "close" else c["high"] > orb_high
        broke_low = c["close"] < orb_low if entry_mode == "close" else c["low"] < orb_low
        if broke_high and broke_low:
            if allow_up and (gap_bias == "buy" or c["close"] >= c["open"]):
                return i, "buy"
            elif allow_down:
                return i, "sell"
            elif allow_up:
                return i, "buy"
        elif broke_high and allow_up:
            return i, "buy"
        elif broke_low and allow_down:
            return i, "sell"
    return None


def _find_support_entry(
    monitor: list[dict], breakout_idx: int, direction: str, entry_cutoff_ts: float, entry_mode: str = "close",
) -> tuple[float, float, int, datetime | None, bool] | None:
    """Scans for the pullback and candidate supporting candles in the breakout direction.

    BUY:  Pullback = red candles.  Supporting candle = first GREEN recovery candle.
          Trigger level = GREEN candle HIGH.
          Entry: any candle CLOSES above that HIGH (close mode)
                 or any candle HIGH breaks it (touch mode).
          In touch mode: if a candle's price moves higher than the previous pullback
          candle's HIGH (big green candle covering pullback), enter immediately.

    SELL: Pullback = green candles.  Supporting candle = first RED rejection candle.
          Trigger level = RED candle LOW.
          Entry: any candle CLOSES below that LOW (close mode)
                 or any candle LOW breaks it (touch mode).
          In touch mode: if a candle's price moves lower than the previous bounce
          candle's LOW (big red candle covering bounce), enter immediately.

    Returns:
      (support_trigger_level, tight_stop, support_candle_idx, triggered_at, is_pullback_level)
      where triggered_at is datetime if already broken historically, else None (candidate waiting for break).
      Returns None if no candidate or pullback has formed yet.
    """
    pullback_count = 0
    pullback_extreme: float | None = None
    candidate: tuple[float, float, int] | None = None
    prev_pullback: dict | None = None
    prev_idx: int | None = None

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
                    return trig_lvl, t_stop, cand_idx, triggered_at, False
                # Did this bar resume the pullback (red candle or lower low)?
                if c["low"] < t_stop or is_red:
                    candidate = None
                    pullback_count += 1
                    pullback_extreme = min(t_stop, c["low"])
                    prev_pullback = c
                    prev_idx = i
                elif is_green:
                    candidate = (trig_lvl, min(t_stop, c["low"]), cand_idx)
            else:
                # In touch mode: if a candle moves higher than previous pullback candle's high, trigger entry!
                if entry_mode == "touch" and pullback_count >= 1 and prev_pullback is not None:
                    if c["high"] > prev_pullback["high"]:
                        t_stop = min(pullback_extreme, c["low"])
                        triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                        return prev_pullback["high"], t_stop, i, triggered_at, True

                if is_red:
                    pullback_count += 1
                    pullback_extreme = c["low"] if pullback_extreme is None else min(pullback_extreme, c["low"])
                    prev_pullback = c
                    prev_idx = i
                elif is_green and pullback_count >= _MIN_PULLBACK_CANDLES:
                    candidate = (c["high"], min(pullback_extreme, c["low"]), i)

        else:  # sell
            if candidate is not None:
                trig_lvl, t_stop, cand_idx = candidate
                triggered = c["close"] < trig_lvl if entry_mode == "close" else c["low"] < trig_lvl
                if triggered:
                    triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                    return trig_lvl, t_stop, cand_idx, triggered_at, False
                # Did this bar resume the bounce/pullback (green candle or higher high)?
                if c["high"] > t_stop or is_green:
                    candidate = None
                    pullback_count += 1
                    pullback_extreme = max(t_stop, c["high"])
                    prev_pullback = c
                    prev_idx = i
                elif is_red:
                    candidate = (trig_lvl, max(t_stop, c["high"]), cand_idx)
            else:
                # In touch mode: if a candle moves lower than previous bounce candle's low, trigger entry!
                if entry_mode == "touch" and pullback_count >= 1 and prev_pullback is not None:
                    if c["low"] < prev_pullback["low"]:
                        t_stop = max(pullback_extreme, c["high"])
                        triggered_at = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
                        return prev_pullback["low"], t_stop, i, triggered_at, True

                if is_green:
                    pullback_count += 1
                    pullback_extreme = c["high"] if pullback_extreme is None else max(pullback_extreme, c["high"])
                    prev_pullback = c
                    prev_idx = i
                elif is_red and pullback_count >= _MIN_PULLBACK_CANDLES:
                    candidate = (c["low"], max(pullback_extreme, c["high"]), i)

    if candidate is not None:
        trig_lvl, t_stop, cand_idx = candidate
        return trig_lvl, t_stop, cand_idx, None, False

    if prev_pullback is not None and pullback_count >= 1 and prev_idx is not None:
        lvl = prev_pullback["high"] if direction == "buy" else prev_pullback["low"]
        t_stop = pullback_extreme if pullback_extreme is not None else (prev_pullback["low"] if direction == "buy" else prev_pullback["high"])
        return lvl, t_stop, prev_idx, None, True

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
    setup_trend: str = "flat",
    gap_bias: str | None = None,
) -> tuple[TradeSetup, dict | None]:
    if gap_bias is None:
        gap_bias = _gap_bias(candles_5m)

    if frozen is not None:
        action = frozen["action"]
        triggered_at = frozen["triggered_at"]
        entry = frozen["entry"]  # Breakout price (BO level)
        stop_loss = frozen["stop_loss"]  # Tight stop loss
        trigger_price = frozen.get("trigger_price")  # Actual pullback entry price
        sl_wide = frozen.get("sl_wide") or (orb_low if action == "buy" else orb_high)

        # Self-healing: if legacy record froze stop_loss identical to sl_wide, recover the tight stop from monitor candles
        if abs(stop_loss - sl_wide) < 0.05:
            bo = _find_breakout(monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts, gap_bias=gap_bias, entry_mode=entry_mode)
            if bo is not None:
                breakout_idx, _ = bo
                support_res = _find_support_entry(monitor, breakout_idx, action, entry_cutoff_ts, entry_mode=entry_mode)
                if support_res is not None:
                    _, tight_stop, _, _, _ = support_res
                    stop_loss = tight_stop

        status = "triggered"
        fill_level = trigger_price if trigger_price is not None else entry
        rationale = (
            f"Broke ORB at ₹{entry:.2f}, pulled back, and entered at support candle level ₹{fill_level:.2f}. "
            f"Stop ₹{stop_loss:.2f}."
        )
    else:
        breakout = _find_breakout(
            monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts,
            gap_bias=gap_bias, entry_mode=entry_mode,
        )
        if breakout is None:
            action = gap_bias if gap_bias is not None else ("buy" if current_price >= vwap else "sell")
            entry = orb_high if action == "buy" else orb_low
            stop_loss = orb_low if action == "buy" else orb_high
            sl_wide = stop_loss
            triggered_at, trigger_price = None, None
            status = "waiting"
            rationale = f"Price still inside opening range ₹{orb_low:.2f}–₹{orb_high:.2f}. Waiting for a decisive break."
        else:
            breakout_idx, action = breakout
            orb_level = orb_high if action == "buy" else orb_low
            stop_loss = orb_low if action == "buy" else orb_high
            sl_wide = stop_loss

            support_res = _find_support_entry(monitor, breakout_idx, action, entry_cutoff_ts, entry_mode=entry_mode)
            if support_res is None:
                triggered_at, trigger_price = None, None
                entry = orb_level
                status = "pending_entry"
                rationale = (
                    f"Broke {'above' if action == 'buy' else 'below'} opening range ₹{orb_level:.2f}. "
                    f"Watching for pullback and first supporting {'green' if action == 'buy' else 'red'} candle."
                )
            else:
                support_trigger_level, tight_stop, support_idx, hist_triggered_at, is_pullback_level = support_res
                stop_loss = tight_stop

                if hist_triggered_at is not None:
                    triggered_at = hist_triggered_at
                    trigger_price = support_trigger_level
                    entry = orb_level
                    status = "triggered"
                    if is_pullback_level:
                        rationale = (
                            f"Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, "
                            f"pulled back to ₹{tight_stop:.2f}, and broke "
                            f"{'above previous pullback candle high' if action == 'buy' else 'below previous pullback candle low'} "
                            f"₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."
                        )
                    else:
                        if action == "buy":
                            mode_desc = "closed above" if entry_mode == "close" else "broke above"
                            ref_desc = "green supporting candle high"
                        else:
                            mode_desc = "closed below" if entry_mode == "close" else "broke below"
                            ref_desc = "red supporting candle low"
                        rationale = (
                            f"Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, "
                            f"pulled back to ₹{tight_stop:.2f}, and {mode_desc} {ref_desc} ₹{support_trigger_level:.2f}. "
                            f"Stop ₹{stop_loss:.2f}."
                        )
                else:
                    # In 'touch' mode, check live LTP against the candidate/pullback support candle
                    if entry_mode == "touch":
                        ltp_crossed = (
                            (action == "buy" and current_price > support_trigger_level) or
                            (action == "sell" and current_price < support_trigger_level)
                        )
                        if ltp_crossed:
                            triggered_at = datetime.now(tz=timezone.utc)
                            trigger_price = support_trigger_level
                            entry = orb_level
                            status = "triggered"
                            if is_pullback_level:
                                rationale = (
                                    f"Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, "
                                    f"pulled back to ₹{tight_stop:.2f}, and LTP broke "
                                    f"{'above previous pullback candle high' if action == 'buy' else 'below previous pullback candle low'} "
                                    f"₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."
                                )
                            else:
                                rationale = (
                                    f"Broke ORB {'high' if action == 'buy' else 'low'} ₹{orb_level:.2f}, "
                                    f"pulled back to ₹{tight_stop:.2f}, and LTP broke "
                                    f"{'above green supporting candle high' if action == 'buy' else 'below red supporting candle low'} "
                                    f"₹{support_trigger_level:.2f}. Stop ₹{stop_loss:.2f}."
                                )
                        else:
                            triggered_at, trigger_price = None, support_trigger_level
                            entry = orb_level
                            status = "pending_entry"
                            if is_pullback_level:
                                rationale = (
                                    f"Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. "
                                    f"Pullback ongoing — waiting for LTP to "
                                    f"{'cross above previous candle high' if action == 'buy' else 'break below previous candle low'} ₹{support_trigger_level:.2f}."
                                )
                            else:
                                rationale = (
                                    f"Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. "
                                    f"{'Green' if action == 'buy' else 'Red'} supporting candle formed — waiting for LTP to "
                                    f"{'cross above' if action == 'buy' else 'break below'} ₹{support_trigger_level:.2f}."
                                )
                    else:
                        # In 'close' mode, wait for the 3m candle to close
                        triggered_at, trigger_price = None, support_trigger_level
                        entry = orb_level
                        status = "pending_entry"
                        if is_pullback_level:
                            rationale = (
                                f"Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. "
                                f"Watching for pullback and first supporting {'green' if action == 'buy' else 'red'} candle."
                            )
                        else:
                            rationale = (
                                f"Broke {'above' if action == 'buy' else 'below'} ORB ₹{orb_level:.2f}. "
                                f"{'Green' if action == 'buy' else 'Red'} supporting candle formed — waiting for 3m candle to "
                                f"{'close above' if action == 'buy' else 'close below'} ₹{support_trigger_level:.2f}."
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


def check_sl_hit(
    monitor: list[dict],
    action: str,
    stop_loss: float,
    triggered_at: datetime,
    trigger_bar_secs: int,
    entry_mode: str = "close",
) -> datetime | None:
    trig_ts = triggered_at.timestamp()
    for c in monitor:
        # In close mode, entry occurs at the close of the trigger candle, so only
        # subsequent candles can hit the stop loss.
        # In touch mode, entry occurs during the trigger candle, so that candle itself can hit SL.
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
    return None
