import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, with_fyers_context
from app.schemas.stock import (
    CandlesResponse,
    Fundamentals,
    IntradaySnapshot,
    IntradaySnapshotsRequest,
    IntradaySnapshotsResponse,
    Quote,
    StockDetails,
    StockSummary,
    SupportLevelsResponse,
)
from app.services import intraday_analysis, market_data, support_levels
from app.services.fyers_client import FyersTokenExpired
from app.services.market_context import get_active_fyers_token
from app.services.notification_client import notify_stop_loss_hit, notify_trade_setup_triggered

router = APIRouter(prefix="/stocks", tags=["stocks"], dependencies=[Depends(with_fyers_context)])


@router.get("/search", response_model=list[StockSummary])
async def search_stocks(q: str = "") -> list[StockSummary]:
    return market_data.search(q)


@router.get("/{symbol}/quote", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    quote = market_data.get_quote(symbol)
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return quote


@router.get("/{symbol}/fundamentals", response_model=Fundamentals)
async def get_fundamentals(symbol: str) -> Fundamentals:
    fundamentals = market_data.get_fundamentals(symbol)
    if fundamentals is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return fundamentals


@router.get("/{symbol}/details", response_model=StockDetails)
async def get_details(
    symbol: str,
    refresh: bool = Query(default=False, description="Force a fresh Yahoo fetch, bypass DB cache."),
) -> StockDetails:
    details = market_data.get_details(symbol, force_refresh=refresh)
    if details is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return details


@router.get("/{symbol}/support-levels", response_model=SupportLevelsResponse)
async def get_support_levels(symbol: str) -> SupportLevelsResponse:
    levels = support_levels.compute_support_levels(symbol)
    if levels is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return levels


@router.get("/{symbol}/candles", response_model=CandlesResponse)
async def get_candles(
    symbol: str,
    period: str = Query(default="1y", description="Period: 1mo, 3mo, 6mo, 1y, 2y, 5y"),
    interval: str = Query(default="1d", description="Interval: 1d (daily)"),
) -> CandlesResponse:
    if not market_data.symbol_exists(symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    candles = market_data.get_candles(symbol, period=period, interval=interval)
    return CandlesResponse(
        symbol=symbol.upper(),
        interval=interval,
        period=period,
        candles=candles,
        fetchedAt=datetime.now(timezone.utc),
    )


async def _require_fyers_token(current_user: dict) -> str:
    token = await get_active_fyers_token(current_user["_id"])
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fyers must be connected for intraday analysis.",
        )
    return token


@router.get("/{symbol}/intraday-snapshot", response_model=IntradaySnapshot)
async def get_intraday_snapshot(
    symbol: str, current_user: dict = Depends(get_current_user)
) -> IntradaySnapshot:
    if not market_data.symbol_exists(symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    token = await _require_fyers_token(current_user)
    try:
        snapshot = await asyncio.to_thread(intraday_analysis.compute_snapshot, symbol, token)
    except FyersTokenExpired:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Fyers session expired.") from None
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No intraday data yet — is the market open?",
        )
    asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snapshot))
    asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snapshot))
    return snapshot


@router.post("/intraday-snapshots", response_model=IntradaySnapshotsResponse)
async def batch_intraday_snapshots(
    payload: IntradaySnapshotsRequest, current_user: dict = Depends(get_current_user)
) -> IntradaySnapshotsResponse:
    if not payload.symbols:
        return IntradaySnapshotsResponse(snapshots={}, fetchedAt=datetime.now(timezone.utc))
    token = await _require_fyers_token(current_user)

    # Each snapshot makes 2 Fyers calls (5m + 3m). Fyers rate-limits at ~10 req/s,
    # so cap to 4 concurrent snapshots = at most 8 in-flight calls.
    sem = asyncio.Semaphore(4)

    async def _one(sym: str) -> tuple[str, IntradaySnapshot | None]:
        async with sem:
            try:
                snap = await asyncio.to_thread(intraday_analysis.compute_snapshot, sym, token)
            except FyersTokenExpired:
                snap = None
        return sym.upper(), snap

    results = await asyncio.gather(*[_one(s) for s in payload.symbols[:50]])
    for _, snap in results:
        if snap is not None:
            asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snap))
            asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snap))
    return IntradaySnapshotsResponse(
        snapshots={sym: snap for sym, snap in results},
        fetchedAt=datetime.now(timezone.utc),
    )
