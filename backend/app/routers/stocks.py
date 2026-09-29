import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.database import get_db
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
    notify_pullback_started,
    notify_stop_loss_hit,
    notify_support_candle_formed,
    notify_trade_setup_triggered,
)
from app.services.order_execution import trigger_autotrade_if_enabled
from app.services.watchlist_processor import watchlist_processor

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
        setup = snapshot.tradeSetup
        if setup:
            if setup.stageKey == "pb_forming":
                asyncio.create_task(asyncio.to_thread(notify_pullback_started, snapshot, current_user["_id"]))
            elif setup.stageKey == "support_formed":
                asyncio.create_task(asyncio.to_thread(notify_support_candle_formed, snapshot, current_user["_id"]))
        asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snapshot, current_user["_id"]))
        asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snapshot, current_user["_id"]))
        asyncio.create_task(trigger_autotrade_if_enabled(snapshot, current_user["_id"], get_db()))
    return snapshot


@router.post("/intraday-snapshots", response_model=IntradaySnapshotsResponse)
async def batch_intraday_snapshots(
    payload: IntradaySnapshotsRequest, current_user: dict = Depends(get_current_user)
) -> IntradaySnapshotsResponse:
    if not payload.symbols:
        return IntradaySnapshotsResponse(snapshots={}, fetchedAt=datetime.now(timezone.utc))
    if not strategies.is_valid_strategy(payload.strategy):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown strategy")

    user_wids = getattr(watchlist_processor, "_user_active_watchlists", {}).get(str(current_user["_id"])) or []
    wid = payload.watchlistId or (user_wids[0] if user_wids else None)
    retest_date = getattr(payload, "retestDate", None)
    entry_mode = getattr(payload, "entryMode", "close") or "close"
    include_first_candle = getattr(payload, "includeFirstCandle", False)

    # Fast path: Serve from processor's pre-computed snapshot cache (<10ms)
    if not retest_date and wid:
        cached_snapshots = watchlist_processor.get_cached_snapshots(wid)
        req_syms = [s.upper() for s in payload.symbols[:50]]
        if cached_snapshots and all(s in cached_snapshots for s in req_syms):
            return IntradaySnapshotsResponse(
                snapshots={s: cached_snapshots[s] for s in req_syms},
                fetchedAt=datetime.now(timezone.utc),
            )

    token = await _require_fyers_token(current_user)

    db = get_db()
    from app.services import trading_service
    trading_cfg = await trading_service.get_user_trading_config(current_user["_id"], db)
    sl_buffer_pct = float(trading_cfg.get("slBufferPct", 25.0))

    # Each snapshot makes 2 Fyers calls (5m + 3m). Fyers rate-limits at ~10 req/s,
    # so cap to 2 concurrent snapshots with slight spacing to prevent 429 errors.
    sem = asyncio.Semaphore(2)

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
                    sl_buffer_pct,
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
                setup = snap.tradeSetup
                if setup:
                    if setup.stageKey == "pb_forming":
                        asyncio.create_task(asyncio.to_thread(notify_pullback_started, snap, user_id, index_snaps))
                    elif setup.stageKey == "support_formed":
                        asyncio.create_task(asyncio.to_thread(notify_support_candle_formed, snap, user_id, index_snaps))
                asyncio.create_task(asyncio.to_thread(notify_trade_setup_triggered, snap, user_id, index_snaps))
                asyncio.create_task(asyncio.to_thread(notify_stop_loss_hit, snap, user_id, index_snaps))
                asyncio.create_task(trigger_autotrade_if_enabled(snap, user_id, get_db()))
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


# ---------------------------------------------------------------------------
# Swing High / Low SL Suggestion  (independent — not wired into trade flows)
# ---------------------------------------------------------------------------

class SwingLevelOut(BaseModel):
    time: str           # HH:MM IST
    price: float
    candleOpen: float
    candleHigh: float
    candleLow: float
    candleClose: float
    distanceFromEntry: float
    gapPct: float


class SwingSLResponse(BaseModel):
    symbol: str
    side: str
    entryPrice: float
    resolution: str
    date: str
    strength: int
    suggestedSL: float | None
    suggestedSLTime: str | None   # "HH:MM" IST or None
    gapPct: float | None
    swingLevels: list[SwingLevelOut]
    fallbackSL: float | None
    fallbackPct: float
    candlesFetched: int
    error: str | None


class SwingAnalyseResponse(BaseModel):
    symbol: str
    date: str
    resolution: str
    strength: int
    totalCandles: int
    swingHighs: list[dict]
    swingLows: list[dict]
    error: str | None = None


@router.get("/{symbol}/swing-sl", response_model=SwingSLResponse, tags=["swing-sl"])
async def get_swing_sl(
    symbol: str,
    side: str = Query(..., description="'buy' or 'sell'"),
    entry_price: float = Query(..., alias="entryPrice", description="Trade entry price"),
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today IST"),
    resolution: str = Query("5", description="Fyers candle resolution in minutes"),
    strength: int = Query(2, description="Pivot look-left/right bar count"),
    fallback_pct: float = Query(0.3, alias="fallbackPct", description="Flat-% SL fallback"),
    current_user: dict = Depends(get_current_user),
) -> SwingSLResponse:
    """Suggest a structurally-backed intraday Stop-Loss using swing pivot points.

    For a SELL/SHORT trade it finds the nearest swing HIGH above entry_price.
    For a BUY/LONG  trade it finds the nearest swing LOW  below entry_price.

    This endpoint is completely independent of the live trade execution flow.
    """
    from app.services.swing_sl import suggest_sl
    from app.services.market_context import get_active_fyers_token

    token = get_active_fyers_token()
    result = await asyncio.to_thread(
        suggest_sl,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        access_token=token,
        date=date,
        resolution=resolution,
        strength=strength,
        fallback_pct=fallback_pct,
    )

    def _fmt_time(dt) -> str | None:
        if dt is None:
            return None
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
        except Exception:
            return dt.strftime("%H:%M")

    levels_out = [
        SwingLevelOut(
            time=_fmt_time(lv.time) or "",
            price=lv.price,
            candleOpen=lv.candle_open,
            candleHigh=lv.candle_high,
            candleLow=lv.candle_low,
            candleClose=lv.candle_close,
            distanceFromEntry=lv.distance_from_entry,
            gapPct=lv.gap_pct,
        )
        for lv in result.swing_levels
    ]

    return SwingSLResponse(
        symbol=result.symbol,
        side=result.side,
        entryPrice=result.entry_price,
        resolution=result.resolution,
        date=result.date,
        strength=result.strength,
        suggestedSL=result.suggested_sl,
        suggestedSLTime=_fmt_time(result.suggested_sl_time),
        gapPct=result.gap_pct,
        swingLevels=levels_out,
        fallbackSL=result.fallback_sl,
        fallbackPct=result.fallback_pct,
        candlesFetched=result.candles_fetched,
        error=result.error,
    )


@router.get("/{symbol}/swing-analyse", response_model=SwingAnalyseResponse, tags=["swing-sl"])
async def analyse_swing_levels(
    symbol: str,
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today IST"),
    resolution: str = Query("5", description="Fyers candle resolution in minutes"),
    strength: int = Query(2, description="Pivot look-left/right bar count"),
    current_user: dict = Depends(get_current_user),
) -> SwingAnalyseResponse:
    """Return ALL intraday swing highs and swing lows for a symbol/date.

    Diagnostic endpoint — useful for understanding the day's price structure
    before choosing an SL level.  Does NOT require an entry_price.
    """
    from app.services.swing_sl import analyse_symbol_swings
    from app.services.market_context import get_active_fyers_token

    token = get_active_fyers_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="Fyers not connected — intraday candles unavailable",
        )

    result = await asyncio.to_thread(
        analyse_symbol_swings,
        symbol=symbol,
        access_token=token,
        date=date,
        resolution=resolution,
        strength=strength,
    )
    return SwingAnalyseResponse(**result)
