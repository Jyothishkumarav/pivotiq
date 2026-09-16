from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db
from app.dependencies import get_current_user, with_fyers_context
from app.schemas.trade import OrderStatus, PortfolioSummary, PositionOut, Segment, TradeCreate, TradeOut
from app.services import market_data, trading_service

router = APIRouter(tags=["paper-trading"], dependencies=[Depends(with_fyers_context)])


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
        if payload.qty > held:
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
    segment: Segment | None = Query(default=None), current_user: dict = Depends(get_current_user)
) -> list[PositionOut]:
    db = get_db()
    await trading_service.fill_pending_limits(db, current_user["_id"])
    query: dict = {"userId": current_user["_id"]}
    if segment is not None:
        query["segment"] = segment.value
    trades = await db.paper_trades.find(query).to_list(length=None)
    return trading_service.compute_positions(trades)


@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    segment: Segment | None = Query(default=None), current_user: dict = Depends(get_current_user)
) -> PortfolioSummary:
    db = get_db()
    await trading_service.fill_pending_limits(db, current_user["_id"])
    trades = await db.paper_trades.find({"userId": current_user["_id"]}).to_list(length=None)
    positions = trading_service.compute_positions(trades)
    return trading_service.compute_portfolio_summary(positions, segment.value if segment else None)
