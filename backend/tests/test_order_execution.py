from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pytest

from app.services.brokers.base import OrderSide, OrderStatus, OrderType, ProductType
from app.services.brokers.fyers_broker import FyersBroker
from app.services.order_execution import calculate_trade_sizing, round_to_tick


def test_round_to_tick():
    assert round_to_tick(100.03) == 100.05
    assert round_to_tick(100.01) == 100.00
    assert round_to_tick(100.08) == 100.10


def test_calculate_trade_sizing_user_spec():
    """Verify user rule:
    Available capital = 10,000, 50% allocation = 5,000 trade capital.
    5x intraday leverage -> purchasing power = 25,000.
    Stock price = 500, tight SL = 480.
    Risk = 20. Buffer = 20% of 20 = 4.
    Buffered SL = 480 - 4 = 476.
    Per share risk = 500 - 476 = 24.
    Max risk allowed = 1,100.
    Qty from capital = floor(25,000 / 500) = 50.
    Qty from risk = floor(1,100 / 24) = 45.
    Final chosen Qty = min(50, 45) = 45.
    Total Risk = 45 * 24 = 1,080 <= 1,100.
    """
    res = calculate_trade_sizing(
        available_capital=10000.0,
        stock_price=500.0,
        tight_sl=480.0,
        capital_allocation_pct=50.0,
        max_risk_amount=1100.0,
        leverage=5.0,
        sl_buffer_pct=20.0,
        side="buy",
    )
    assert res.bufferedSl == 476.0
    assert res.riskPerShare == 24.0
    assert res.tradeCapital == 5000.0
    assert res.purchasingPower == 25000.0
    assert res.qty == 45
    assert res.totalRisk == 1080.0
    assert res.totalRisk <= 1100.0
    assert res.affordable is True


def test_calculate_trade_sizing_capital_constraint():
    """When capital is the binding constraint rather than risk."""
    res = calculate_trade_sizing(
        available_capital=2000.0,
        stock_price=1000.0,
        tight_sl=990.0,
        capital_allocation_pct=50.0,  # 1,000 capital -> 5x leverage = 5,000 buying power
        max_risk_amount=1100.0,
        leverage=5.0,
        sl_buffer_pct=20.0,
        side="buy",
    )
    # 5,000 / 1000 = 5 shares
    assert res.qty == 5
    assert res.marginRequired == 1000.0
    assert res.tradeCapital == 1000.0
    assert res.affordable is True


def test_fyers_broker_mapping():
    broker = FyersBroker(access_token="test_token")

    # 1. Market order mapping
    req_mkt = MagicMock(
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
    )
    ft, lp, sp = broker._map_order_type_and_prices(req_mkt)
    assert ft == 2
    assert lp == 0.0
    assert sp == 0.0

    # 2. Stop Loss (SL-M) mapping
    req_sl = MagicMock(
        order_type=OrderType.SL_M,
        limit_price=None,
        stop_price=488.5,
    )
    ft, lp, sp = broker._map_order_type_and_prices(req_sl)
    assert ft == 3
    assert lp == 0.0
    assert sp == 488.5

    # 3. Limit order mapping
    req_lim = MagicMock(
        order_type=OrderType.LIMIT,
        limit_price=500.0,
        stop_price=None,
    )
    ft, lp, sp = broker._map_order_type_and_prices(req_lim)
    assert ft == 1
    assert lp == 500.0
    assert sp == 0.0


@pytest.mark.anyio
async def test_fyers_broker_intraday_enforced():
    broker = FyersBroker(access_token="test_token")
    req = MagicMock(
        symbol="TCS",
        qty=1,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        product_type="CNC",  # Delivery should be rejected!
    )
    with pytest.raises(ValueError, match="Only INTRADAY"):
        await broker.place_order(req)


@pytest.mark.anyio
async def test_execute_buy_and_sl_order_chain():
    """Verify Buy order is placed and SL order immediately follows with 20% buffered SL."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from app.services.brokers.base import BaseBroker, BrokerFunds, BrokerOrderResponse

    now = datetime(2026, 9, 25, 4, 30, tzinfo=timezone.utc)
    mock_broker = MagicMock(spec=BaseBroker)
    mock_broker.broker_name = "test_broker"
    mock_broker.get_funds = AsyncMock(
        return_value=BrokerFunds(
            broker="test_broker",
            available_balance=10000.0,
            total_balance=10000.0,
            buying_power_5x=50000.0,
        )
    )

    # First call: Buy order response
    buy_resp = BrokerOrderResponse(
        order_id="BUY_12345",
        broker="test_broker",
        symbol="RELIANCE",
        qty=45,
        price=500.0,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        product_type="INTRADAY",
        status=OrderStatus.FILLED,
        placed_at=now,
    )
    # Second call: SL order response
    sl_resp = BrokerOrderResponse(
        order_id="SL_67890",
        broker="test_broker",
        symbol="RELIANCE",
        qty=45,
        price=476.0,
        stop_price=476.0,
        side=OrderSide.SELL,
        order_type=OrderType.SL_M,
        product_type="INTRADAY",
        status=OrderStatus.OPEN,
        parent_order_id="BUY_12345",
        placed_at=now,
    )

    mock_broker.place_order = AsyncMock(side_effect=[buy_resp, sl_resp])

    from app.services.order_execution import execute_buy_and_sl_order

    result = await execute_buy_and_sl_order(
        broker=mock_broker,
        symbol="RELIANCE",
        stock_price=500.0,
        tight_sl=480.0,
        capital_allocation_pct=50.0,
        max_risk_amount=1100.0,
        sl_buffer_pct=20.0,
        strategy="orb_pullback_support",
        triggered_at=now,
    )

    assert result.status == "success"
    assert result.buyOrder.order_id == "BUY_12345"
    assert result.slOrder is not None
    assert result.slOrder.order_id == "SL_67890"
    assert result.slOrder.stop_price == 476.0  # 480 - (20 * 0.20)
    assert result.sizing.qty == 45
    assert mock_broker.place_order.call_count == 2


@pytest.mark.anyio
async def test_paper_broker_simulated_execution():
    """Verify PaperBroker execution and order cancellation."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from bson import ObjectId
    from app.services.brokers.paper_broker import PaperBroker
    from app.services.brokers.base import BrokerOrderRequest, OrderPurpose

    db = MagicMock()
    db.paper_orders.insert_one = AsyncMock()
    db.paper_trades.insert_one = AsyncMock()

    update_res = MagicMock()
    update_res.modified_count = 1
    db.paper_orders.update_one = AsyncMock(return_value=update_res)
    db.paper_orders.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    db.paper_trades.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))

    now = datetime(2026, 9, 25, 4, 30, tzinfo=timezone.utc)
    user_id = ObjectId()
    broker = PaperBroker(user_id=user_id, db=db)

    # 1. Place Market BUY
    buy_req = BrokerOrderRequest(
        symbol="SBIN",
        qty=10,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        product_type=ProductType.INTRADAY,
        placed_at=now,
    )
    buy_res = await broker.place_order(buy_req)
    assert buy_res.status == OrderStatus.FILLED
    assert buy_res.filled_qty == 10
    assert db.paper_orders.insert_one.call_count == 1
    assert db.paper_trades.insert_one.call_count == 1

    # 2. Place SL order
    sl_req = BrokerOrderRequest(
        symbol="SBIN",
        qty=10,
        side=OrderSide.SELL,
        order_type=OrderType.SL_M,
        stop_price=780.0,
        product_type=ProductType.INTRADAY,
        parent_order_id=buy_res.order_id,
        purpose=OrderPurpose.STOP_LOSS,
        placed_at=now,
    )
    sl_res = await broker.place_order(sl_req)
    assert sl_res.status == OrderStatus.OPEN
    assert db.paper_orders.insert_one.call_count == 2

    # 3. Cancel open SL order
    cancelled = await broker.cancel_order(sl_res.order_id)
    assert cancelled is True


@pytest.mark.anyio
async def test_is_symbol_autotrade_enabled():
    from app.services.order_execution import is_symbol_autotrade_enabled
    db = MagicMock()
    user_id = ObjectId()

    # Case 1: Symbol has autoTrade=True
    db.watchlists.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Intraday"})
    res = await is_symbol_autotrade_enabled(user_id, "TATASTEEL", db)
    assert res is True

    # Case 2: Symbol has autoTrade=False or not found
    db.watchlists.find_one = AsyncMock(return_value=None)
    res = await is_symbol_autotrade_enabled(user_id, "INFY", db)
    assert res is False



