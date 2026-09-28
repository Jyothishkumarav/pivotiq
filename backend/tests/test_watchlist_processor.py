import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from bson import ObjectId

from app.schemas.stock import IntradaySnapshot, TradeSetup
from app.services.watchlist_processor import WatchlistProcessor
from app.services.notification_client import (
    notify_pullback_started,
    notify_support_candle_formed,
)
from app.services.order_execution import trigger_autotrade_if_enabled


def _create_mock_snapshot(
    symbol: str = "TCS",
    strategy: str = "orb_pullback_support",
    stage_key: str = "triggered",
    entry: float = 3500.0,
    sl: float = 3470.0,
    ltp: float = 3510.0,
    action: str = "buy",
) -> IntradaySnapshot:
    setup = TradeSetup(
        strategy=strategy,
        action=action,
        status="triggered" if stage_key == "triggered" else "waiting",
        bias="bullish" if action == "buy" else "bearish",
        entry=entry,
        stopLoss=sl,
        target=entry + (entry - sl) * 2,
        triggerPrice=entry,
        riskRewardRatio=2.0,
        vwapPosition="above",
        rationale="Test setup rationale",
        slWide=None,
        stageKey=stage_key,
        stage=5 if stage_key == "triggered" else 4 if stage_key == "support_formed" else 3,
        stageLabel="Test Stage",
        stageDesc="Test Stage Description",
        triggeredAt=datetime(2026, 9, 25, 4, 30, tzinfo=timezone.utc),
    )
    return IntradaySnapshot(
        symbol=symbol,
        currentPrice=ltp,
        openingRangeHigh=3520.0,
        openingRangeLow=3460.0,
        openingRangeClose=3500.0,
        dayHigh=3520.0,
        dayLow=3460.0,
        trend="up",
        candleCount=15,
        updatedAt=datetime(2026, 9, 25, 4, 30, tzinfo=timezone.utc),
        vwap=3495.0,
        changePercent=0.3,
        tradeSetup=setup,
    )


def test_watchlist_processor_in_memory_mutations():
    wp = WatchlistProcessor()
    wid = "test_wid_123"
    uid = "test_user_456"

    # Seed initial metadata
    wp._watchlist_meta[wid] = {"symbols": [], "autoTrades": {}, "strategy": "orb_pullback_support", "userId": uid}

    # 1. Switch active watchlist
    wp.switch_active_watchlist(uid, wid)
    assert wp._user_active_watchlist[uid] == wid

    # 2. Add stock
    wp.notify_stock_added(wid, "INFY", auto_trade=False)
    assert "INFY" in wp._watchlist_meta[wid]["symbols"]
    assert wp._watchlist_meta[wid]["autoTrades"]["INFY"] is False

    # 3. Toggle autotrade
    wp.notify_autotrade_toggled(wid, "INFY", auto_trade=True)
    assert wp._watchlist_meta[wid]["autoTrades"]["INFY"] is True

    # 4. Snapshots caching
    mock_snap = _create_mock_snapshot("INFY")
    wp.set_cached_snapshots(wid, {"INFY": mock_snap})
    cached = wp.get_cached_snapshots(wid)
    assert cached is not None
    assert "INFY" in cached

    # 5. Remove stock
    wp.notify_stock_removed(wid, "INFY")
    assert "INFY" not in wp._watchlist_meta[wid]["symbols"]
    assert wp.get_cached_snapshots(wid) is None


def test_progressive_stage_notifications():
    snap_pb = _create_mock_snapshot("RELIANCE", stage_key="pb_forming")
    snap_sup = _create_mock_snapshot("RELIANCE", stage_key="support_formed")

    with patch("app.services.notification_client.requests.post") as mock_post, \
         patch("app.services.notification_client.get_cache_client") as mock_cache:
        
        cache_instance = MagicMock()
        cache_instance.exists.return_value = False
        mock_cache.return_value = cache_instance
        mock_post.return_value.ok = True

        # Test pullback started notification
        notify_pullback_started(snap_pb, user_id=ObjectId())
        assert mock_post.call_count == 1
        call_args = mock_post.call_args[1]["json"]
        assert "Pullback Started" in call_args["title"]
        assert call_args["metadata"]["stage"] == "pb_forming"

        # Test support candle formed notification
        notify_support_candle_formed(snap_sup, user_id=ObjectId())
        assert mock_post.call_count == 2
        call_args_sup = mock_post.call_args[1]["json"]
        assert "Support Formed" in call_args_sup["title"]
        assert call_args_sup["metadata"]["stage"] == "support_formed"


@pytest.mark.anyio
async def test_dual_execution_paper_always_and_fyers_conditional():
    """Verify that paper trade ALWAYS executes, and Fyers is only called if is_live_trade is True."""
    user_id = ObjectId()
    wid = "test_wid_dual"
    snap = _create_mock_snapshot("SBIN", stage_key="triggered")

    mock_db = MagicMock()
    mock_db.user_settings.find_one = AsyncMock(return_value={"config": {"activeWatchlistId": wid}})
    mock_db.watchlists.find_one = AsyncMock(return_value={
        "_id": ObjectId(),
        "items": [{"symbol": "SBIN", "autoTrade": False}]
    })
    mock_db.paper_orders.find_one = AsyncMock(return_value=None)
    mock_db.order_chains.find_one = AsyncMock(return_value=None)

    with patch("app.services.order_execution.execute_order_with_sl", new_callable=AsyncMock) as mock_exec, \
         patch("app.services.cache.get_cache_client") as mock_cache:

        mock_cache_inst = MagicMock()
        mock_cache_inst.exists.return_value = False
        mock_cache.return_value = mock_cache_inst

        # Case 1: autoTrade is False (Paper only)
        await trigger_autotrade_if_enabled(snap, user_id, mock_db)
        assert mock_exec.call_count == 1
        # broker passed should be PaperBroker
        broker_used = mock_exec.call_args[1]["broker"]
        assert broker_used.broker_name == "paper"

        # Case 2: autoTrade is True (Dual execution: Paper AND Fyers)
        mock_db.watchlists.find_one = AsyncMock(return_value={
            "_id": ObjectId(),
            "items": [{"symbol": "SBIN", "autoTrade": True}]
        })
        mock_cache_inst.exists.return_value = False
        mock_exec.reset_mock()

        with patch("app.services.brokers.factory.get_active_fyers_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "fake_fyers_token"
            await trigger_autotrade_if_enabled(snap, user_id, mock_db)

            # Both Paper and Fyers execution calls should be made
            assert mock_exec.call_count == 2
            brokers = [call[1]["broker"].broker_name for call in mock_exec.call_args_list]
            assert "paper" in brokers
            assert "fyers" in brokers
