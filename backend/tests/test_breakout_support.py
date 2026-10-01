import pytest
from datetime import datetime, timezone

from app.services.strategies import breakout_support


def test_initial_breakout_down_sell():
    orb_high = 25000.0
    orb_low = 24900.0
    orb_close_ts = 1000.0
    entry_cutoff_ts = 5000.0

    # 3m candle closing below orb_low
    monitor = [
        {"ts": 1000.0, "open": 24920.0, "high": 24930.0, "low": 24880.0, "close": 24885.0, "volume": 100.0},
    ]

    breakout_info = breakout_support._find_dynamic_breakout(
        monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts
    )
    assert breakout_info is not None
    idx, direction, has_reversed = breakout_info
    assert idx == 0
    assert direction == "sell"
    assert has_reversed is False


def test_dynamic_reversal_sell_to_buy():
    orb_high = 25000.0
    orb_low = 24900.0
    orb_close_ts = 1000.0
    entry_cutoff_ts = 5000.0

    monitor = [
        # Candle 0: Breaks Low -> initial breakout SELL
        {"ts": 1000.0, "open": 24920.0, "high": 24930.0, "low": 24880.0, "close": 24885.0, "volume": 100.0},
        # Candle 1: Pullback bounce
        {"ts": 1180.0, "open": 24885.0, "high": 24950.0, "low": 24880.0, "close": 24940.0, "volume": 100.0},
        # Candle 2: Dynamic Reversal: 3m candle closes ABOVE orb_high!
        {"ts": 1360.0, "open": 24940.0, "high": 25020.0, "low": 24930.0, "close": 25010.0, "volume": 150.0},
    ]

    breakout_info = breakout_support._find_dynamic_breakout(
        monitor, orb_high, orb_low, orb_close_ts, entry_cutoff_ts
    )
    assert breakout_info is not None
    idx, direction, has_reversed = breakout_info
    assert idx == 2
    assert direction == "buy"
    assert has_reversed is True


def test_compute_setup_dynamic_reversal_recalculates_levels():
    orb_high = 25000.0
    orb_low = 24900.0
    orb_close_ts = 1000.0
    entry_cutoff_ts = 5000.0

    monitor = [
        # Candle 0: Breaks Low -> initial breakout SELL
        {"ts": 1000.0, "open": 24920.0, "high": 24930.0, "low": 24880.0, "close": 24885.0, "volume": 100.0},
        # Candle 1: Bounce
        {"ts": 1180.0, "open": 24885.0, "high": 24950.0, "low": 24880.0, "close": 24940.0, "volume": 100.0},
        # Candle 2: Dynamic Reversal: closes ABOVE orb_high
        {"ts": 1360.0, "open": 24940.0, "high": 25020.0, "low": 24930.0, "close": 25010.0, "volume": 150.0},
        # Candle 3: Red pullback candle for BUY
        {"ts": 1540.0, "open": 25010.0, "high": 25015.0, "low": 24980.0, "close": 24985.0, "volume": 100.0},
        # Candle 4: First GREEN supporting candle (High=25005, Low=24982)
        {"ts": 1720.0, "open": 24985.0, "high": 25005.0, "low": 24982.0, "close": 25000.0, "volume": 120.0},
    ]

    # Stale frozen state from prior SELL
    frozen_sell = {
        "action": "sell",
        "triggered_at": datetime(2026, 10, 1, 4, 15, tzinfo=timezone.utc),
        "entry": 24900.0,
        "stop_loss": 24950.0,
        "trigger_price": 24890.0,
        "sl_wide": 25000.0,
    }

    setup, freeze_payload = breakout_support.compute_setup(
        symbol="NIFTY 50",
        candles_5m=[],
        monitor=monitor,
        orb_high=orb_high,
        orb_low=orb_low,
        orb_close_ts=orb_close_ts,
        vwap=24990.0,
        current_price=25000.0,
        trigger_bar_secs=180,
        entry_cutoff_ts=entry_cutoff_ts,
        frozen=frozen_sell,  # Previous SELL state
        entry_mode="close",
        sl_buffer_pct=25.0,
    )

    # Must be flipped to BUY
    assert setup.action == "buy"
    assert setup.bias == "bullish"
    # BO level is now ORB High (25000)
    assert setup.entry == 25000.0
    # MSL is now ORB Low (24900)
    assert setup.slWide == 24900.0
    # Stage 4: Support Formed (green candle high = 25005)
    assert setup.stage == 4
    assert setup.stageKey == "support_formed"
    assert setup.triggerPrice == 25005.0
    # Tight stop loss is pullback low (24980) minus buffer
    assert setup.stopLoss < 24980.0
