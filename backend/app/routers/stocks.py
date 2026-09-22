import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

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
from app.services import intraday_analysis, market_data, strategies, support_levels
from app.services.fyers_client import FyersTokenExpired
from app.services.market_context import get_active_fyers_token
from app.services.notification_client import (
    clear_notification_cache,
    notify_stop_loss_hit,
    notify_trade_setup_triggered,
)

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
    symbol: str,
    strategy: str = Query(default="orb_vwap"),
    entry_mode: str = Query(default="close", pattern="^(touch|close)$"),
    include_first_candle: bool = Query(default=False),
    retest_date: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> IntradaySnapshot:
    if not market_data.symbol_exists(symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    if not strategies.is_valid_strategy(strategy):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown strategy")
    token = await _require_fyers_token(current_user)
    try:
        snapshot = await asyncio.to_thread(
            intraday_analysis.compute_snapshot,
            symbol,
            token,
            strategy,
            entry_mode,
            retest_date,
            include_first_candle,
        )
    except FyersTokenExpired:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Fyers session expired.") from None
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No intraday data found for this date.",
        )
    if not retest_date:
        asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snapshot, current_user["_id"]))
        asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snapshot, current_user["_id"]))
    return snapshot


@router.post("/intraday-snapshots", response_model=IntradaySnapshotsResponse)
async def batch_intraday_snapshots(
    payload: IntradaySnapshotsRequest, current_user: dict = Depends(get_current_user)
) -> IntradaySnapshotsResponse:
    if not payload.symbols:
        return IntradaySnapshotsResponse(snapshots={}, fetchedAt=datetime.now(timezone.utc))
    if not strategies.is_valid_strategy(payload.strategy):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown strategy")
    token = await _require_fyers_token(current_user)

    # Each snapshot makes 2 Fyers calls (5m + 3m). Fyers rate-limits at ~10 req/s,
    # so cap to 2 concurrent snapshots with slight spacing to prevent 429 errors.
    sem = asyncio.Semaphore(2)
    entry_mode = getattr(payload, "entryMode", "close") or "close"
    include_first_candle = getattr(payload, "includeFirstCandle", False)
    retest_date = getattr(payload, "retestDate", None)

    async def _one(sym: str) -> tuple[str, IntradaySnapshot | None]:
        async with sem:
            try:
                await asyncio.sleep(0.10)
                snap = await asyncio.to_thread(
                    intraday_analysis.compute_snapshot,
                    sym,
                    token,
                    payload.strategy,
                    entry_mode,
                    retest_date,
                    include_first_candle,
                )
            except FyersTokenExpired:
                snap = None
        return sym.upper(), snap

    user_id = current_user["_id"]
    results = await asyncio.gather(*[_one(s) for s in payload.symbols[:50]])
    if not retest_date:
        index_snaps = {
            sym: snap for sym, snap in results
            if snap is not None and sym in ("NIFTY50", "BANKNIFTY", "NIFTY 50", "BANK NIFTY")
        }
        for sym, snap in results:
            if snap is not None:
                if sym in ("NIFTY50", "BANKNIFTY", "NIFTY 50", "BANK NIFTY"):
                    continue
                asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snap, user_id, index_snaps))
                asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snap, user_id, index_snaps))
    return IntradaySnapshotsResponse(
        snapshots={sym: snap for sym, snap in results},
        fetchedAt=datetime.now(timezone.utc),
    )


class ClearTriggersRequest(BaseModel):
    strategy: str
    date: str | None = None      # ISO date, e.g. "2026-09-18". None = all dates.
    symbols: list[str] | None = None  # None = all symbols for this strategy/date


class ClearTriggersResponse(BaseModel):
    deleted: int
    message: str


@router.delete("/intraday-triggers", response_model=ClearTriggersResponse)
async def clear_intraday_triggers(
    payload: ClearTriggersRequest,
    current_user: dict = Depends(get_current_user),
) -> ClearTriggersResponse:
    """Delete frozen trigger records from MongoDB and evict them from the
    in-memory cache so the very next snapshot call re-evaluates from raw candles.

    Use this after changing strategy logic to force revalidation without
    waiting for the next trading day.
    """
    if not strategies.is_valid_strategy(payload.strategy):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown strategy")

    deleted = await asyncio.to_thread(
        intraday_analysis.clear_frozen_triggers,
        strategy=payload.strategy,
        date=payload.date,
        symbols=payload.symbols,
    )

    # Also wipe the per-symbol snapshot cache so the refreshed data
    # is fetched fresh on the very next poll.
    intraday_analysis.invalidate_snapshot_cache(
        strategy=payload.strategy,
        symbols=payload.symbols,
    )

    # Wipe notification deduplication cache from Redis so alerts can re-fire
    await asyncio.to_thread(
        clear_notification_cache,
        strategy=payload.strategy,
        symbols=payload.symbols,
    )

    symbol_desc = f"{len(payload.symbols)} symbol(s)" if payload.symbols else "all symbols"
    date_desc = payload.date or "all dates"
    return ClearTriggersResponse(
        deleted=deleted,
        message=f"Cleared {deleted} frozen trigger(s) for {payload.strategy} / {date_desc} / {symbol_desc}.",
    )
