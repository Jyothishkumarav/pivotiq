from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.strategy import (
    STRATEGY_DISPLAY_NAMES,
    StrategyAutoTradeItem,
    StrategyAutoTradeResponse,
    StrategyAutoTradeUpdate,
    StrategyChannelUpdate,
    StrategyName,
    StrategyNotificationItem,
    StrategyNotificationsResponse,
    StrategyNotificationUpdate,
    TelegramChannelOption,
)
from app.services import market_data
from app.services.strategies import STRATEGY_NAMES
from app.services.watchlist_processor import watchlist_processor

AVAILABLE_TELEGRAM_CHANNELS: list[TelegramChannelOption] = [
    TelegramChannelOption(id="-1003999053085", name="FyersTrade"),
    TelegramChannelOption(id="-1004449069761", name="Pivotiq_Tuned"),
    TelegramChannelOption(id="-1004294022390", name="PivotIQ_15_Mins_Break"),
    TelegramChannelOption(id="-1004440440854", name="Pivotiqupdate"),
]

DEFAULT_STRATEGY_CHANNELS: dict[str, str] = {
    "breakout_support": "-1004449069761",
    "orb_pullback_support": "-1004440440854",
    "orb_pullback": "-1004294022390",
}

DEFAULT_STRATEGY_CHANNEL_NAMES: dict[str, str] = {
    "breakout_support": "Pivotiq_Tuned",
    "orb_pullback_support": "Pivotiqupdate",
    "orb_pullback": "PivotIQ_15_Mins_Break",
}

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


class DataSourceOut(BaseModel):
    mode: Literal["real", "mock"]


class DataSourceIn(BaseModel):
    mode: Literal["real", "mock"]


@router.get("/data-source", response_model=DataSourceOut)
async def get_data_source() -> DataSourceOut:
    return DataSourceOut(mode=market_data.get_mode())


@router.put("/data-source", response_model=DataSourceOut)
async def set_data_source(payload: DataSourceIn) -> DataSourceOut:
    market_data.set_mode(payload.mode)
    return DataSourceOut(mode=market_data.get_mode())


def _get_user_enabled_set(user_id: str, doc: dict | None) -> set[str]:
    if doc and "enabledStrategies" in doc:
        return set(doc["enabledStrategies"])
    # Default: strategies enabled in config or defaults
    settings = get_settings()
    configured = settings.notification_enabled_strategies
    if configured:
        return set(configured)
    return set(STRATEGY_NAMES)


@router.get("/strategy-notifications", response_model=StrategyNotificationsResponse)
async def get_strategy_notifications(
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await _get_channel_doc(db, user_id)
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels, channel_names = _get_strategy_channels(doc)

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
            telegramChannelName=channel_names.get(s.value),
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(
        strategies=items,
        availableChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


@router.put("/strategy-notifications", response_model=StrategyNotificationsResponse)
async def update_strategy_notification(
    payload: StrategyNotificationUpdate,
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    valid_keys = {s.value for s in StrategyName}
    if payload.key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid strategy key: {payload.key!r}",
        )

    db = get_db()
    user_id = str(current_user["_id"])
    doc = await _get_channel_doc(db, user_id)
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels, channel_names = _get_strategy_channels(doc)

    if payload.enabled:
        enabled_set.add(payload.key)
    else:
        enabled_set.discard(payload.key)

    if doc and "_id" in doc:
        await db.user_settings.update_one(
            {"_id": doc["_id"]},
            {"$set": {"enabledStrategies": list(enabled_set), "userId": user_id}},
        )
    else:
        await db.user_settings.update_one(
            {"userId": user_id, "type": "strategy_notifications"},
            {"$set": {"enabledStrategies": list(enabled_set)}},
            upsert=True,
        )

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
            telegramChannelName=channel_names.get(s.value),
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(
        strategies=items,
        availableChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


def _get_strategy_channels(doc: dict | None) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({strategy_key: channel_id}, {strategy_key: channel_name}) from user_settings doc,
    falling back to DEFAULT_STRATEGY_CHANNELS."""
    ids = dict(DEFAULT_STRATEGY_CHANNELS)
    names = dict(DEFAULT_STRATEGY_CHANNEL_NAMES)
    if doc and "strategyChannels" in doc and isinstance(doc["strategyChannels"], dict):
        ids.update(doc["strategyChannels"])
    if doc and "strategyChannelNames" in doc and isinstance(doc["strategyChannelNames"], dict):
        names.update(doc["strategyChannelNames"])
    return ids, names


def _resolve_telegram_title(chat_id: str) -> str | None:
    """Resolve Telegram channel title from available list or Telegram API."""
    for ch in AVAILABLE_TELEGRAM_CHANNELS:
        if ch.id == chat_id:
            return ch.name

    import os
    import requests as _req
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    try:
        r = _req.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
            timeout=5,
        )
        data = r.json()
        if data.get("ok"):
            return data["result"].get("title")
    except Exception:
        pass
    return None


async def _get_channel_doc(db, user_id: str) -> dict | None:
    """Fetch user_settings doc for strategy_notifications.
    Tries user-scoped doc (str or ObjectId), then falls back to any doc."""
    from bson import ObjectId
    conds: list[dict] = [{"userId": user_id}]
    if ObjectId.is_valid(user_id):
        conds.append({"userId": ObjectId(user_id)})
    doc = await db.user_settings.find_one({"type": "strategy_notifications", "$or": conds})
    if doc is None:
        doc = await db.user_settings.find_one({
            "type": "strategy_notifications",
            "$or": [{"userId": {"$exists": False}}, {"userId": None}, {"userId": ""}],
        })
    if doc is None:
        doc = await db.user_settings.find_one({"type": "strategy_notifications"})
    return doc


@router.get("/strategy-channels", response_model=StrategyNotificationsResponse)
async def get_strategy_channels(
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await _get_channel_doc(db, user_id)
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels, channel_names = _get_strategy_channels(doc)

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
            telegramChannelName=channel_names.get(s.value),
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(
        strategies=items,
        availableChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


@router.put("/strategy-channels", response_model=StrategyNotificationsResponse)
async def update_strategy_channel(
    payload: StrategyChannelUpdate,
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    valid_keys = {s.value for s in StrategyName}
    if payload.key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid strategy key: {payload.key!r}",
        )

    db = get_db()
    user_id = str(current_user["_id"])
    doc = await _get_channel_doc(db, user_id)
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels, channel_names = _get_strategy_channels(doc)

    if payload.telegramChannelId:
        cid = payload.telegramChannelId.strip()
        channels[payload.key] = cid
        resolved_name = (
            payload.telegramChannelName.strip()
            if payload.telegramChannelName
            else _resolve_telegram_title(cid)
        )
        if resolved_name:
            channel_names[payload.key] = resolved_name
        else:
            channel_names.pop(payload.key, None)
    else:
        # Fall back to default
        default_id = DEFAULT_STRATEGY_CHANNELS.get(payload.key)
        default_name = DEFAULT_STRATEGY_CHANNEL_NAMES.get(payload.key)
        if default_id:
            channels[payload.key] = default_id
            if default_name:
                channel_names[payload.key] = default_name
        else:
            channels.pop(payload.key, None)
            channel_names.pop(payload.key, None)

    if doc and "_id" in doc:
        await db.user_settings.update_one(
            {"_id": doc["_id"]},
            {"$set": {"strategyChannels": channels, "strategyChannelNames": channel_names, "userId": user_id}},
        )
    else:
        await db.user_settings.update_one(
            {"userId": user_id, "type": "strategy_notifications"},
            {"$set": {"strategyChannels": channels, "strategyChannelNames": channel_names}},
            upsert=True,
        )

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
            telegramChannelName=channel_names.get(s.value),
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(
        strategies=items,
        availableChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


AVAILABLE_BROKERS = [
    {"id": "paper", "name": "PivotIQ Paper Trading (Simulated)"},
    {"id": "fyers", "name": "Fyers Securities (API v3)"},
]


@router.get("/strategy-autotrade", response_model=StrategyAutoTradeResponse)
async def get_strategy_autotrade(
    current_user: dict = Depends(get_current_user),
) -> StrategyAutoTradeResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_autotrade"})
    configs = doc.get("configs", {}) if doc else {}

    items: list[StrategyAutoTradeItem] = []
    for s in StrategyName:
        strat_cfg = configs.get(s.value, {})
        items.append(
            StrategyAutoTradeItem(
                key=s.value,
                label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
                enabled=bool(strat_cfg.get("enabled", False)),
                broker=str(strat_cfg.get("broker", "paper")),
                capitalAllocationPct=float(strat_cfg.get("capitalAllocationPct", 50.0)),
                maxRiskPerTrade=float(strat_cfg.get("maxRiskPerTrade", 1100.0)),
                slBufferPct=float(strat_cfg.get("slBufferPct", 20.0)),
                leverage=5.0,
                productType="INTRADAY",
            )
        )
    return StrategyAutoTradeResponse(strategies=items, availableBrokers=AVAILABLE_BROKERS)


@router.put("/strategy-autotrade", response_model=StrategyAutoTradeResponse)
async def update_strategy_autotrade(
    payload: StrategyAutoTradeUpdate,
    current_user: dict = Depends(get_current_user),
) -> StrategyAutoTradeResponse:
    valid_keys = {s.value for s in StrategyName}
    if payload.key not in valid_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid strategy key: {payload.key!r}")

    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_autotrade"})
    configs = doc.get("configs", {}) if doc else {}

    strat_cfg = dict(configs.get(payload.key, {}))
    if payload.enabled is not None:
        strat_cfg["enabled"] = payload.enabled
    if payload.broker is not None:
        strat_cfg["broker"] = payload.broker
    if payload.capitalAllocationPct is not None:
        strat_cfg["capitalAllocationPct"] = max(1.0, min(100.0, float(payload.capitalAllocationPct)))
    if payload.maxRiskPerTrade is not None:
        strat_cfg["maxRiskPerTrade"] = max(100.0, float(payload.maxRiskPerTrade))
    if payload.slBufferPct is not None:
        strat_cfg["slBufferPct"] = max(0.0, float(payload.slBufferPct))

    strat_cfg["leverage"] = 5.0
    strat_cfg["productType"] = "INTRADAY"
    configs[payload.key] = strat_cfg

    await db.user_settings.update_one(
        {"userId": user_id, "type": "strategy_autotrade"},
        {"$set": {"configs": configs, "userId": user_id}},
        upsert=True,
    )

    items: list[StrategyAutoTradeItem] = []
    for s in StrategyName:
        sc = configs.get(s.value, {})
        items.append(
            StrategyAutoTradeItem(
                key=s.value,
                label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
                enabled=bool(sc.get("enabled", False)),
                broker=str(sc.get("broker", "paper")),
                capitalAllocationPct=float(sc.get("capitalAllocationPct", 50.0)),
                maxRiskPerTrade=float(sc.get("maxRiskPerTrade", 1100.0)),
                slBufferPct=float(sc.get("slBufferPct", 20.0)),
                leverage=5.0,
                productType="INTRADAY",
            )
        )
    return StrategyAutoTradeResponse(strategies=items, availableBrokers=AVAILABLE_BROKERS)


class WatchlistOption(BaseModel):
    id: str
    name: str
    itemCount: int


class TradingSettingsResponse(BaseModel):
    paperCapital: float
    slBufferPct: float
    maxRiskPerTrade: float
    maxOpenPositions: int
    activeWatchlistId: str | None
    entryMode: str = "close"
    availableWatchlists: list[WatchlistOption]
    # Swing SL settings
    swingSlEnabled: bool = False
    swingSlBufferPct: float = 1.0  # % added on top of detected swing level
    # Telegram Trade Alerts settings
    tradeTelegramChannelId: str | None = "-1003999053085"
    tradeTelegramChannelName: str | None = "FyersTrade"
    tradeTelegramAlertsEnabled: bool = True
    availableTelegramChannels: list[TelegramChannelOption] = AVAILABLE_TELEGRAM_CHANNELS


class TradingSettingsUpdate(BaseModel):
    paperCapital: float | None = None
    slBufferPct: float | None = None
    maxRiskPerTrade: float | None = None
    maxOpenPositions: int | None = None
    activeWatchlistId: str | None = None
    entryMode: str | None = None
    # Swing SL settings
    swingSlEnabled: bool | None = None
    swingSlBufferPct: float | None = None
    # Telegram Trade Alerts settings
    tradeTelegramChannelId: str | None = None
    tradeTelegramChannelName: str | None = None
    tradeTelegramAlertsEnabled: bool | None = None


@router.get("/trading", response_model=TradingSettingsResponse)
async def get_trading_settings(current_user: dict = Depends(get_current_user)) -> TradingSettingsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "trading_config"})
    cfg = doc.get("config", {}) if doc else {}

    user_ids = [user_id]
    if ObjectId.is_valid(user_id):
        user_ids.append(ObjectId(user_id))
    watchlists = await db.watchlists.find({"userId": {"$in": user_ids}}).to_list(100)
    wl_options = [
        WatchlistOption(id=str(w["_id"]), name=w.get("name", "Untitled"), itemCount=len(w.get("items", [])))
        for w in watchlists
    ]

    return TradingSettingsResponse(
        paperCapital=float(cfg.get("paperCapital", 100_000.0)),
        slBufferPct=float(cfg.get("slBufferPct", 25.0)),
        maxRiskPerTrade=float(cfg.get("maxRiskPerTrade", 1100.0)),
        maxOpenPositions=int(cfg.get("maxOpenPositions", 10)),
        activeWatchlistId=cfg.get("activeWatchlistId"),
        entryMode=str(cfg.get("entryMode", "close")),
        availableWatchlists=wl_options,
        swingSlEnabled=bool(cfg.get("swingSlEnabled", False)),
        swingSlBufferPct=float(cfg.get("swingSlBufferPct", 1.0)),
        tradeTelegramChannelId=str(cfg.get("tradeTelegramChannelId", "-1003999053085")),
        tradeTelegramChannelName=str(cfg.get("tradeTelegramChannelName", "FyersTrade")),
        tradeTelegramAlertsEnabled=bool(cfg.get("tradeTelegramAlertsEnabled", True)),
        availableTelegramChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


@router.put("/trading", response_model=TradingSettingsResponse)
async def update_trading_settings(
    payload: TradingSettingsUpdate,
    current_user: dict = Depends(get_current_user),
) -> TradingSettingsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "trading_config"})
    cfg = dict(doc.get("config", {})) if doc else {}

    if payload.paperCapital is not None:
        cfg["paperCapital"] = max(10_000.0, float(payload.paperCapital))
    if payload.slBufferPct is not None:
        cfg["slBufferPct"] = max(1.0, min(100.0, float(payload.slBufferPct)))
    if payload.maxRiskPerTrade is not None:
        cfg["maxRiskPerTrade"] = max(100.0, float(payload.maxRiskPerTrade))
    if payload.maxOpenPositions is not None:
        cfg["maxOpenPositions"] = max(1, min(50, int(payload.maxOpenPositions)))
    if payload.activeWatchlistId is not None:
        cfg["activeWatchlistId"] = payload.activeWatchlistId if payload.activeWatchlistId not in ("all", "") else None
        watchlist_processor.switch_active_watchlist(user_id, cfg["activeWatchlistId"])
    if payload.entryMode is not None:
        cfg["entryMode"] = "touch" if payload.entryMode == "touch" else "close"
    if payload.swingSlEnabled is not None:
        cfg["swingSlEnabled"] = bool(payload.swingSlEnabled)
    if payload.swingSlBufferPct is not None:
        cfg["swingSlBufferPct"] = max(0.0, min(20.0, float(payload.swingSlBufferPct)))
    if payload.tradeTelegramChannelId is not None:
        cfg["tradeTelegramChannelId"] = payload.tradeTelegramChannelId.strip()
    if payload.tradeTelegramChannelName is not None:
        cfg["tradeTelegramChannelName"] = payload.tradeTelegramChannelName.strip()
    if payload.tradeTelegramAlertsEnabled is not None:
        cfg["tradeTelegramAlertsEnabled"] = bool(payload.tradeTelegramAlertsEnabled)

    now = datetime.now(timezone.utc)
    await db.user_settings.update_one(
        {"userId": user_id, "type": "trading_config"},
        {"$set": {"config": cfg, "userId": user_id, "updatedAt": now}},
        upsert=True,
    )

    user_ids = [user_id]
    if ObjectId.is_valid(user_id):
        user_ids.append(ObjectId(user_id))
    watchlists = await db.watchlists.find({"userId": {"$in": user_ids}}).to_list(100)
    wl_options = [
        WatchlistOption(id=str(w["_id"]), name=w.get("name", "Untitled"), itemCount=len(w.get("items", [])))
        for w in watchlists
    ]

    return TradingSettingsResponse(
        paperCapital=float(cfg.get("paperCapital", 100_000.0)),
        slBufferPct=float(cfg.get("slBufferPct", 25.0)),
        maxRiskPerTrade=float(cfg.get("maxRiskPerTrade", 1100.0)),
        maxOpenPositions=int(cfg.get("maxOpenPositions", 10)),
        activeWatchlistId=cfg.get("activeWatchlistId"),
        entryMode=str(cfg.get("entryMode", "close")),
        availableWatchlists=wl_options,
        swingSlEnabled=bool(cfg.get("swingSlEnabled", False)),
        swingSlBufferPct=float(cfg.get("swingSlBufferPct", 1.0)),
        tradeTelegramChannelId=str(cfg.get("tradeTelegramChannelId", "-1003999053085")),
        tradeTelegramChannelName=str(cfg.get("tradeTelegramChannelName", "FyersTrade")),
        tradeTelegramAlertsEnabled=bool(cfg.get("tradeTelegramAlertsEnabled", True)),
        availableTelegramChannels=AVAILABLE_TELEGRAM_CHANNELS,
    )


@router.post("/trading/test-telegram")
async def test_trading_telegram_alert(current_user: dict = Depends(get_current_user)) -> dict:
    from app.services.notification_client import notify_trade_execution
    user_id = str(current_user["_id"])
    success = notify_trade_execution(
        symbol="HDFCBANK",
        side="buy",
        qty=10,
        entry_price=1745.50,
        stop_loss=1738.00,
        strategy="orb_pullback_support",
        broker="PivotIQ (Test Trade Alert)",
        user_id=user_id,
        is_test=True,
    )
    return {
        "ok": success,
        "message": "Test trade alert successfully sent to Telegram channel!"
        if success
        else "Failed to send test alert. Please check your Telegram channel configuration and bot permissions.",
    }

