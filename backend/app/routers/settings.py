from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.strategy import (
    STRATEGY_DISPLAY_NAMES,
    StrategyChannelUpdate,
    StrategyName,
    StrategyNotificationItem,
    StrategyNotificationsResponse,
    StrategyNotificationUpdate,
    TelegramChannelOption,
)
from app.services import market_data
from app.services.strategies import STRATEGY_NAMES

AVAILABLE_TELEGRAM_CHANNELS: list[TelegramChannelOption] = [
    TelegramChannelOption(id="-1004449069761", name="Pivotiq_Tuned"),
    TelegramChannelOption(id="-1004294022390", name="PivotIQ_15_Mins_Break"),
    TelegramChannelOption(id="-1004440440854", name="Pivotiqupdate"),
]

DEFAULT_STRATEGY_CHANNELS: dict[str, str] = {
    "orb_flow": "-1004449069761",
    "orb_pullback_support": "-1004440440854",
    "orb_pullback": "-1004294022390",
}

DEFAULT_STRATEGY_CHANNEL_NAMES: dict[str, str] = {
    "orb_flow": "Pivotiq_Tuned",
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
