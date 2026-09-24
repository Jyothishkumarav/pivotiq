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
)
from app.services import market_data
from app.services.strategies import STRATEGY_NAMES

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
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_notifications"})
    enabled_set = _get_user_enabled_set(user_id, doc)

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(strategies=items)


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
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_notifications"})
    enabled_set = _get_user_enabled_set(user_id, doc)

    if payload.enabled:
        enabled_set.add(payload.key)
    else:
        enabled_set.discard(payload.key)

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
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(strategies=items)


def _get_strategy_channels(doc: dict | None) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({strategy_key: channel_id}, {strategy_key: channel_name}) from user_settings doc."""
    ids = dict(doc["strategyChannels"]) if doc and "strategyChannels" in doc else {}
    names = dict(doc["strategyChannelNames"]) if doc and "strategyChannelNames" in doc else {}
    return ids, names


def _resolve_telegram_title(chat_id: str) -> str | None:
    """Call Telegram getChat to resolve the group/channel title. Best-effort, returns None on failure."""
    import requests as _req
    settings = get_settings()
    # Reuse bot token from notification-service env via the settings chain
    # The token lives in TELEGRAM_BOT_TOKEN (notification-service env), forwarded via .env
    import os
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


@router.get("/strategy-channels", response_model=StrategyNotificationsResponse)
async def get_strategy_channels(
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_notifications"})
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
    return StrategyNotificationsResponse(strategies=items)


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
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_notifications"})
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels, channel_names = _get_strategy_channels(doc)

    if payload.telegramChannelId:
        cid = payload.telegramChannelId.strip()
        channels[payload.key] = cid
        # Resolve human-readable name: prefer caller-supplied, else fetch from Telegram
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
        channels.pop(payload.key, None)      # clear → fall back to global default
        channel_names.pop(payload.key, None)

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
    return StrategyNotificationsResponse(strategies=items)
