"""ORB + VWAP Pullback strategy — same gap-up/gap-down and opening-range
breakout direction logic as `orb_vwap`, but the ENTRY itself is different:
instead of entering right at the ORB breakout, this strategy waits for the
inevitable pullback after the breakout and enters on the first candle that
confirms the pullback is over, giving a better (closer to the pre-breakout
level) entry price than chasing the initial breakout candle.

This module is purely additive and fully self-contained — it does not import
from, or get imported by, `orb_vwap`'s inline logic or `context_gated`. Both
of those remain completely untouched.

Design:
  1. Gap-up/gap-down + strong, well-supported first-candle conviction gate —
     identical rule to `orb_vwap`'s own gap-bias override (duplicated here on
     purpose, not shared, so this strategy can evolve independently): if the
     first 5-min candle is a strong, high-volume move in one direction, the
     opposite ORB breakout is suppressed for the whole day.
  2. ORB breakout: same swing-high/low (`orb_high`/`orb_low`) box as
     `orb_vwap`. The first 3-min candle whose CLOSE clears that box (in an
     allowed direction) marks the breakout.
  3. Pullback entry: starting the candle right after the breakout, wait for
     at least one candle against the breakout direction (a "pullback"
     candle), then enter on the first candle back in the breakout's own
     direction (the "reversal" candle) — e.g. breakout up -> one or more red
     candles -> first green candle -> buy at that candle's close. Mirrored
     for a breakdown (green pullback candles -> first red candle -> sell).
     The stop-loss is the extreme of the pullback candles themselves (the
     low for a buy, the high for a sell) — a tight, structurally-meaningful
     stop right at the pullback's own low/high.
  4. Status lifecycle exposed via `TradeSetup.status`:
       "waiting"       — no ORB breakout yet.
       "pending_entry" — breakout confirmed, direction locked, watching the
                         monitor bars for the pullback + reversal candle.
       "triggered"     — the reversal candle closed, entry recorded.
       "sl_hit"        — (set by the caller via `check_sl_hit`, same pattern
                         as `orb_vwap`/`context_gated`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.stock import TradeSetup

_GAP_BIAS_MIN_CANDLES = 6
_GAP_BIAS_MIN_MOVE_PCT = 0.5
_GAP_BIAS_BODY_FRACTION = 0.5
_GAP_BIAS_CLOSE_POSITION = 0.6
_MIN_PULLBACK_CANDLES = 1  # at least this many opposite-colour candles before the reversal candle counts


def _gap_bias(candles_5m: list[dict]) -> str | None:
    """Same rule as `orb_vwap`'s gap-bias override (see that module's
    docstring for the full rationale) — deliberately duplicated, not
    imported, so this strategy stays fully independent."""
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
    """First candle (index into `monitor`) whose CLOSE clears the ORB box in
    an allowed direction. Returns (index, "buy"|"sell") or None."""
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


def _find_pullback(
    monitor: list[dict], breakout_idx: int, direction: str, entry_cutoff_ts: float,
) -> tuple[float, float, int] | None:
    """Phase 1: scan for the pullback structure after the ORB breakout.

    Looks for >= `_MIN_PULLBACK_CANDLES` opposite-colour candles after the
    breakout and extracts the structural trigger level and tight stop:
      BUY:  trigger_level = HIGH  of the first red pullback candle
            tight_stop    = lowest LOW of all pullback red candles
      SELL: trigger_level = LOW   of the first green pullback candle
            tight_stop    = highest HIGH of all pullback green candles

    Returns (trigger_level, tight_stop, last_pullback_candle_idx)
    or None if no qualifying pullback has formed yet."""
    pullback_count = 0
    pullback_extreme: float | None = None
    trigger_level:   float | None = None
    last_pb_idx = breakout_idx

    for i in range(breakout_idx + 1, len(monitor)):
        c = monitor[i]
        if c["ts"] >= entry_cutoff_ts:
            break
        is_red   = c["close"] < c["open"]
        is_green = c["close"] > c["open"]

        if direction == "buy":
            if is_red:
                pullback_count += 1
                last_pb_idx = i
                pullback_extreme = c["low"] if pullback_extreme is None else min(pullback_extreme, c["low"])
                if trigger_level is None:
                    trigger_level = c["high"]  # HIGH of the first red candle = level to break
            else:
                # Non-red candle ends the pullback phase — stop collecting
                if pullback_count >= _MIN_PULLBACK_CANDLES:
                    break  # pullback complete; cross-detection happens in compute_setup
                else:
                    # pullback interrupted before reaching minimum — reset
                    pullback_count = 0
                    pullback_extreme = None
                    trigger_level = None
        else:  # sell
            if is_green:
                pullback_count += 1
                last_pb_idx = i
                pullback_extreme = c["high"] if pullback_extreme is None else max(pullback_extreme, c["high"])
                if trigger_level is None:
                    trigger_level = c["low"]  # LOW of the first green candle = level to break
            else:
                if pullback_count >= _MIN_PULLBACK_CANDLES:
                    break
                else:
                    pullback_count = 0
                    pullback_extreme = None
                    trigger_level = None

    if pullback_count >= _MIN_PULLBACK_CANDLES and trigger_level is not None and pullback_extreme is not None:
        return trigger_level, pullback_extreme, last_pb_idx
    return None


def _find_level_cross(
    monitor: list[dict], after_idx: int, direction: str,
    trigger_level: float, entry_cutoff_ts: float, trigger_bar_secs: int,
) -> tuple[datetime, float] | None:
    """Phase 2: find the first candle after the pullback whose HIGH (BUY)
    or LOW (SELL) crosses `trigger_level` — i.e. the moment price first
    touched/exceeded the structural level, intrabar.

    Returns (triggered_at, trigger_level) where:
      triggered_at = open-time of that bar (earliest possible touch)
      trigger_level = the structural level (fill price for a stop-buy/stop-sell order)
    or None if no historical candle has crossed yet."""
    for c in monitor[after_idx + 1:]:
        if c["ts"] >= entry_cutoff_ts:
            break
        if direction == "buy" and c["high"] > trigger_level:
            ts = datetime.fromtimestamp(c["ts"], tz=timezone.utc)  # bar OPEN = earliest touch
            return ts, trigger_level
        if direction == "sell" and c["low"] < trigger_level:
            ts = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
            return ts, trigger_level
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
    # ORB macro stops: the structural level identified in the first 20 min.
    # For BUY the main SL is the ORB Low; for SELL it is the ORB High.
    # These are set as `slWide` on the TradeSetup so the UI can display both
    # the tight pullback stop and this wider structural stop together.
    orb_macro_sl_buy  = orb_low
    orb_macro_sl_sell = orb_high
    gap_bias = _gap_bias(candles_5m)

    if frozen is not None:
        # Frozen state from DB: entry = ORB breakout level (threshold), trigger_price = reversal fill
        action = frozen["action"]
        triggered_at = frozen["triggered_at"]
        entry = frozen["entry"]                       # ORB breakout close — threshold level
        stop_loss = frozen["stop_loss"]               # tight pullback extreme stop
        trigger_price = frozen.get("trigger_price")  # actual fill at structural level
        # sl_wide may be absent on records frozen before this field was added;
        # fall back to recomputing from the current ORB levels.
        sl_wide = frozen.get("sl_wide") or (orb_low if action == "buy" else orb_high)
        status = "triggered"
        _main_sl_note = f" · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})" if sl_wide else ""
        rationale = (
            f"Broke the opening range at ₹{entry:.2f}, pulled back, "
            f"then LTP broke the pullback level ₹{trigger_price:.2f}.{_main_sl_note}"
            if trigger_price is not None
            else f"Breakout + pullback entry, tight stop ₹{stop_loss:.2f} (the pullback's own extreme)."
        )
    else:
        breakout = _find_breakout(monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts, gap_bias)
        if breakout is None:
            # No breakout yet — entry = ORB threshold to break, SL = opposite ORB level
            action    = gap_bias if gap_bias is not None else ("buy" if current_price >= vwap else "sell")
            entry     = orb_high if action == "buy" else orb_low
            stop_loss = orb_low  if action == "buy" else orb_high
            sl_wide   = stop_loss  # same as stop_loss before triggered
            triggered_at, trigger_price = None, None
            status = "waiting"
            rationale = "No ORB breakout yet — waiting for a decisive close beyond the opening range."
        else:
            breakout_idx, action = breakout
            # entry = ORB breakout candle's close (threshold, "E" in UI)
            # sl_wide = the macro ORB level (structural stop from the first 20 min)
            orb_break_price = monitor[breakout_idx]["close"]
            sl_wide = orb_macro_sl_buy if action == "buy" else orb_macro_sl_sell

            pullback = _find_pullback(monitor, breakout_idx, action, entry_cutoff_ts)
            if pullback is None:
                # Breakout confirmed, watching for pullback formation
                triggered_at, trigger_price = None, None
                entry     = orb_break_price
                stop_loss = sl_wide  # use macro SL until tight stop is known
                status = "pending_entry"
                rationale = (
                    f"Broke {'above' if action == 'buy' else 'below'} the opening range at ₹{orb_break_price:.2f}. "
                    f"Watching for a pullback — entry when LTP breaks the first pullback candle's "
                    f"{'high' if action == 'buy' else 'low'}."
                )
            else:
                pb_trigger_level, tight_stop, last_pb_idx = pullback

                # Phase 2: detect when price first crossed the trigger level.
                # We check candle HIGHs (historical) first — the first bar whose high
                # exceeds the level is when LTP could have triggered a stop-buy order.
                # If no historical bar has crossed yet, fall through to the live LTP check.
                cross = _find_level_cross(
                    monitor, last_pb_idx, action, pb_trigger_level, entry_cutoff_ts, trigger_bar_secs,
                )

                if cross is None:
                    # No historical candle has crossed yet — check live LTP right now.
                    ltp_crossed = (
                        (action == "buy"  and current_price > pb_trigger_level) or
                        (action == "sell" and current_price < pb_trigger_level)
                    )
                    if ltp_crossed:
                        # LTP just broke the level in the current (incomplete) bar.
                        triggered_at  = datetime.now(tz=timezone.utc)
                        trigger_price = pb_trigger_level  # fill at the structural level
                        entry         = orb_break_price
                        stop_loss     = tight_stop
                        status = "triggered"
                        rationale = (
                            f"Broke the opening range at ₹{orb_break_price:.2f}, pulled back, "
                            f"then LTP crossed the pullback level ₹{pb_trigger_level:.2f}. "
                            f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                        )
                    else:
                        # Pullback formed but trigger level not yet broken — still watching.
                        triggered_at, trigger_price = None, None
                        entry     = orb_break_price
                        stop_loss = tight_stop  # tight stop now known from pullback
                        status = "pending_entry"
                        rationale = (
                            f"Broke {'above' if action == 'buy' else 'below'} the opening range at ₹{orb_break_price:.2f}. "
                            f"Pullback formed — waiting for LTP to break ₹{pb_trigger_level:.2f} "
                            f"(first pullback candle's {'high' if action == 'buy' else 'low'}) to enter."
                        )
                else:
                    # Historical candle already crossed the level — entry confirmed.
                    triggered_at, trigger_price = cross  # (bar open time, pb_trigger_level)
                    entry     = orb_break_price
                    stop_loss = tight_stop
                    status = "triggered"
                    rationale = (
                        f"Broke the opening range at ₹{orb_break_price:.2f}, pulled back, "
                        f"then LTP broke the pullback level ₹{pb_trigger_level:.2f}. "
                        f"Tight stop ₹{tight_stop:.2f} · main stop ₹{sl_wide:.2f} (ORB {'low' if action == 'buy' else 'high'})."
                    )

    # R:R and target are computed from the actual fill price (trigger_price) once triggered,
    # or from the entry threshold while still waiting/pending — mirrors orb_vwap behaviour.
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
        strategy="orb_pullback",
        conviction=None,
        gapClass="up" if gap_bias == "buy" else "down" if gap_bias == "sell" else None,
        confirmation="pullback_reversal" if status == "triggered" else None,
        slWide=round(sl_wide, 2) if sl_wide is not None else None,
        triggerPrice=round(trigger_price, 2) if trigger_price is not None else None,
    )

    freeze_payload = None
    if frozen is None and status == "triggered":
        freeze_payload = {
            "triggered_at": triggered_at,
            "action": action,
            "entry": entry,                    # ORB breakout close (threshold)
            "stop_loss": stop_loss,            # tight pullback extreme
            "trigger_price": trigger_price,    # actual fill (structural level break)
            "sl_wide": sl_wide,                # macro ORB stop (orb_low for buy, orb_high for sell)
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
