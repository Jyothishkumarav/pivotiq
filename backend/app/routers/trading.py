import asyncio
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import get_current_user, with_fyers_context
from app.schemas.trade import OrderStatus, PortfolioSummary, PositionOut, Segment, TradeCreate, TradeNotificationOut, TradeOut
from app.services import market_data, trading_service
from app.services.brokers import (
    BaseBroker,
    BrokerFunds,
    BrokerOrderRequest,
    BrokerOrderResponse,
    OrderPurpose,
    OrderSide,
    OrderType,
    ProductType,
    get_broker,
)
from app.services.order_execution import (
    ExecuteOrderResult,
    TradeSizingResult,
    calculate_trade_sizing,
    execute_buy_and_sl_order,
    execute_exit_order,
    execute_sell_exit_order,
    sync_watchlist_entered_trades,
)

router = APIRouter(tags=["trading"], dependencies=[Depends(with_fyers_context)])


def _to_out(doc: dict) -> TradeOut:
    return TradeOut(
        id=str(doc["_id"]),
        userId=str(doc["userId"]),
        symbol=doc["symbol"],
        segment=doc["segment"],
        side=doc["side"],
        qty=doc["qty"],
        price=doc["price"],
        orderType=doc["orderType"],
        status=doc["status"],
        executedAt=doc["executedAt"],
    )


class TradeSizingRequest(BaseModel):
    symbol: str
    stockPrice: float = Field(gt=0)
    tightSl: float = Field(gt=0)
    broker: str = "paper"
    capitalAllocationPct: float = 50.0
    maxRiskPerTrade: float = 1100.0
    slBufferPct: float = 20.0
    side: str = "buy"


class ExecuteOrderRequest(BaseModel):
    symbol: str
    stockPrice: float = Field(gt=0)
    tightSl: float = Field(gt=0)
    qty: int | None = None
    broker: str = "paper"  # "fyers" | "paper"
    capitalAllocationPct: float = 50.0
    maxRiskPerTrade: float = 1100.0
    slBufferPct: float = 20.0
    strategy: str | None = None


class ExitPositionRequest(BaseModel):
    symbol: str
    broker: str = "paper"
    strategy: str | None = None
    exitPrice: float | None = None


@router.get("/trades/funds", response_model=BrokerFunds)
async def get_broker_funds(
    broker: str = Query(default="paper"),
    date: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> BrokerFunds:
    """Fetch current account balances, margin limits, and 5x buying power."""
    db = get_db()
    broker_client = await get_broker(broker, current_user["_id"], db)
    try:
        return await broker_client.get_funds(target_date=date)
    except TypeError:
        return await broker_client.get_funds()


@router.post("/trades/calculate-size", response_model=TradeSizingResult)
async def calculate_size(
    payload: TradeSizingRequest,
    current_user: dict = Depends(get_current_user),
) -> TradeSizingResult:
    """Preview position sizing, 20% buffered SL, and max risk per trade."""
    db = get_db()
    broker_client = await get_broker(payload.broker, current_user["_id"], db)
    funds = await broker_client.get_funds()

    available_capital = funds.available_balance
    return calculate_trade_sizing(
        available_capital=available_capital,
        stock_price=payload.stockPrice,
        tight_sl=payload.tightSl,
        capital_allocation_pct=payload.capitalAllocationPct,
        max_risk_amount=payload.maxRiskPerTrade,
        leverage=5.0,
        sl_buffer_pct=payload.slBufferPct,
        side=payload.side,
    )


@router.post("/trades/execute", response_model=ExecuteOrderResult)
async def execute_order(
    payload: ExecuteOrderRequest,
    current_user: dict = Depends(get_current_user),
) -> ExecuteOrderResult:
    """Executes Buy order + immediately places SL order (strictly Intraday MIS)."""
    db = get_db()
    broker_client = await get_broker(payload.broker, current_user["_id"], db)

    return await execute_buy_and_sl_order(
        broker=broker_client,
        symbol=payload.symbol.upper(),
        stock_price=payload.stockPrice,
        tight_sl=payload.tightSl,
        qty=payload.qty,
        capital_allocation_pct=payload.capitalAllocationPct,
        max_risk_amount=payload.maxRiskPerTrade,
        sl_buffer_pct=payload.slBufferPct,
        strategy=payload.strategy,
        db=db,
        user_id=current_user["_id"],
    )


@router.get("/trades/orders", response_model=list[BrokerOrderResponse])
async def list_orders(
    broker: str = Query(default="paper"),
    date: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[BrokerOrderResponse]:
    """Fetch order book (Buy, SL, Sell orders) for the selected broker."""
    db = get_db()
    broker_client = await get_broker(broker, current_user["_id"], db)
    try:
        return await broker_client.get_orders(target_date=date)
    except TypeError:
        return await broker_client.get_orders()


@router.post("/trades/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    broker: str = Query(default="paper"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel an open order (e.g. pending SL or limit order)."""
    db = get_db()
    broker_client = await get_broker(broker, current_user["_id"], db)
    success = await broker_client.cancel_order(order_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to cancel order")
    return {"success": True, "orderId": order_id}


@router.post("/trades/positions/exit", response_model=BrokerOrderResponse)
async def exit_position(
    payload: ExitPositionRequest,
    current_user: dict = Depends(get_current_user),
) -> BrokerOrderResponse:
    """Exit an open position (Long or Short) with a market order and cancel any active SL order."""
    db = get_db()
    broker_client = await get_broker(payload.broker, current_user["_id"], db)
    positions = await broker_client.get_positions()
    pos = next((p for p in positions if p.symbol == payload.symbol.upper()), None)
    if not pos or pos.netQty == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No open intraday position found for {payload.symbol.upper()}",
        )

    is_long = pos.netQty > 0
    exit_side = OrderSide.SELL if is_long else OrderSide.BUY
    sl_side = OrderSide.SELL if is_long else OrderSide.BUY

    order_type = OrderType.LIMIT if (payload.exitPrice is not None and payload.exitPrice > 0) else OrderType.MARKET
    limit_price = round(float(payload.exitPrice), 2) if order_type == OrderType.LIMIT else None

    # 1. Place exit order
    exit_res = await execute_exit_order(
        broker=broker_client,
        symbol=pos.symbol,
        qty=abs(pos.netQty),
        side=exit_side,
        strategy=payload.strategy,
        order_type=order_type,
        limit_price=limit_price,
    )

    # 2. Cancel any pending SL orders for this symbol
    orders = await broker_client.get_orders()
    for o in orders:
        if o.symbol == pos.symbol and o.status == OrderStatus.OPEN and o.side == sl_side:
            await broker_client.cancel_order(o.order_id)

    return exit_res


@router.post("/trades", response_model=TradeOut, status_code=status.HTTP_201_CREATED)
async def place_trade(payload: TradeCreate, current_user: dict = Depends(get_current_user)) -> TradeOut:
    quote = market_data.get_quote(payload.symbol)
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    if payload.orderType == "limit" and payload.limitPrice is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limitPrice is required for limit orders")

    db = get_db()

    if payload.side == "sell":
        existing_trades = await db.paper_trades.find(
            {"userId": current_user["_id"], "symbol": payload.symbol.upper(), "segment": payload.segment}
        ).to_list(length=None)
        positions = trading_service.compute_positions(existing_trades)
        held = next((p.netQty for p in positions if p.symbol == payload.symbol.upper()), 0)
        if payload.qty > held and held > 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot sell more than held ({held})")

    fill_price, fill_status = trading_service.resolve_fill_price(
        payload.orderType.value, payload.side.value, payload.limitPrice, quote.ltp
    )

    doc = {
        "userId": current_user["_id"],
        "symbol": payload.symbol.upper(),
        "segment": payload.segment.value,
        "side": payload.side.value,
        "qty": payload.qty,
        "price": fill_price,
        "orderType": payload.orderType.value,
        "status": fill_status,
        "executedAt": datetime.now(timezone.utc),
    }
    result = await db.paper_trades.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_out(doc)


@router.get("/trades", response_model=list[TradeOut])
async def list_trades(current_user: dict = Depends(get_current_user)) -> list[TradeOut]:
    db = get_db()
    await trading_service.fill_pending_limits(db, current_user["_id"])
    cursor = db.paper_trades.find({"userId": current_user["_id"]}).sort("executedAt", -1)
    return [_to_out(doc) async for doc in cursor]


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    segment: Segment | None = Query(default=None),
    broker: str = Query(default="paper"),
    date: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> list[PositionOut]:
    db = get_db()
    # Fast non-blocking background auto-sync
    asyncio.create_task(sync_watchlist_entered_trades(current_user["_id"], db, target_date=date))

    if broker.lower() == "fyers":
        broker_client = await get_broker("fyers", current_user["_id"], db)
        positions = await broker_client.get_positions()
        if segment is not None:
            positions = [p for p in positions if p.segment == segment]
        return positions

    from app.services.brokers.paper_broker import PaperBroker
    paper_broker = PaperBroker(user_id=current_user["_id"], db=db)
    positions = await paper_broker.get_positions(target_date=date)
    if segment is not None:
        positions = [p for p in positions if p.segment == segment]
    return positions


@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    segment: Segment | None = Query(default=None),
    broker: str = Query(default="paper"),
    date: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> PortfolioSummary:
    db = get_db()
    if broker.lower() == "fyers":
        broker_client = await get_broker("fyers", current_user["_id"], db)
        positions = await broker_client.get_positions()
        return trading_service.compute_portfolio_summary(positions, segment.value if segment else None)

    from app.services.brokers.paper_broker import PaperBroker
    paper_broker = PaperBroker(user_id=current_user["_id"], db=db)
    positions = await paper_broker.get_positions(target_date=date)
    return trading_service.compute_portfolio_summary(positions, segment.value if segment else None)


@router.post("/trades/paper/reset")
async def reset_paper_account(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Resets paper trading portfolio: cancels open orders, purges paper trades, and resets capital."""
    db = get_db()
    user_ids = [current_user["_id"], str(current_user["_id"])]
    if ObjectId.is_valid(str(current_user["_id"])):
        user_ids.append(ObjectId(str(current_user["_id"])))

    del_trades = await db.paper_trades.delete_many({"userId": {"$in": user_ids}})
    del_orders = await db.paper_orders.delete_many({"userId": {"$in": user_ids}})
    await db.order_chains.delete_many({"userId": {"$in": user_ids}, "broker": "paper"})

    try:
        from app.services.cache import get_cache_client
        cache = get_cache_client()
        if cache:
            cache.delete_pattern("autotrade:paper:*")
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Paper trading account successfully reset to ₹1,00,000 capital.",
        "deletedTrades": del_trades.deleted_count,
        "deletedOrders": del_orders.deleted_count,
    }


@router.get("/trades/notifications", response_model=list[TradeNotificationOut])
async def list_trade_notifications(
    current_user: dict = Depends(get_current_user),
) -> list[TradeNotificationOut]:
    db = get_db()
    user_ids = [current_user["_id"], str(current_user["_id"])]
    if ObjectId.is_valid(str(current_user["_id"])):
        user_ids.append(ObjectId(str(current_user["_id"])))

    today_utc = datetime.now(timezone.utc).date()
    start_of_day = datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=timezone.utc)

    # 1. Fetch from db.trade_notifications
    docs = await db.trade_notifications.find({
        "userId": {"$in": user_ids},
        "placedAt": {"$gte": start_of_day},
    }).sort("placedAt", -1).to_list(100)

    # 2. If no notifications recorded yet (or prior trades exist in order_chains), backfill from order_chains
    if not docs:
        chains = await db.order_chains.find({
            "userId": {"$in": user_ids},
            "placedAt": {"$gte": start_of_day},
        }).sort("placedAt", -1).to_list(100)
        for c in chains:
            sym = str(c.get("symbol", "")).upper()
            side = str(c.get("side", "buy")).lower()
            qty = int(c.get("qty", 1))
            price = float(c.get("stockPrice", 0.0))
            sl = float(c.get("bufferedSl", 0.0) or c.get("tightSl", 0.0))
            fyers_sym = f"NSE:{sym}-EQ"
            docs.append({
                "_id": c["_id"],
                "symbol": sym,
                "fyersSymbol": fyers_sym,
                "fyersUrl": f"https://fyers.in/web/symbol/{fyers_sym}",
                "side": side,
                "qty": qty,
                "entryPrice": price,
                "stopLoss": sl,
                "strategy": c.get("strategy"),
                "placedAt": c.get("placedAt") or datetime.now(timezone.utc),
                "read": False,
                "status": "triggered",
                "message": f"{side.upper()} {qty} {sym} @ ₹{price:.2f} | SL ₹{sl:.2f}",
            })

    out = []
    for d in docs:
        out.append(TradeNotificationOut(
            id=str(d.get("_id", "")),
            symbol=d.get("symbol", "").upper(),
            fyersSymbol=d.get("fyersSymbol") or f"NSE:{d.get('symbol', '').upper()}-EQ",
            fyersUrl=d.get("fyersUrl") or f"https://fyers.in/web/symbol/NSE:{d.get('symbol', '').upper()}-EQ",
            side=str(d.get("side", "buy")).lower(),
            qty=int(d.get("qty", 1)),
            entryPrice=float(d.get("entryPrice", 0.0)),
            stopLoss=float(d.get("stopLoss", 0.0)),
            strategy=d.get("strategy"),
            time=d.get("placedAt") or datetime.now(timezone.utc),
            status=d.get("status", "triggered"),
            message=d.get("message") or f"{str(d.get('side', 'buy')).upper()} {d.get('symbol', '')}",
            read=bool(d.get("read", False)),
        ))
    return out


@router.post("/trades/notifications/mark-read")
async def mark_trade_notifications_read(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    db = get_db()
    user_ids = [current_user["_id"], str(current_user["_id"])]
    if ObjectId.is_valid(str(current_user["_id"])):
        user_ids.append(ObjectId(str(current_user["_id"])))
    await db.trade_notifications.update_many(
        {"userId": {"$in": user_ids}},
        {"$set": {"read": True}},
    )
    return {"status": "ok"}
