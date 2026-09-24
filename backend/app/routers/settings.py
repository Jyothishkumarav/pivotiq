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


def _get_strategy_channels(doc: dict | None) -> dict[str, str]:
    """Return {strategy_key: telegram_channel_id} from user_settings doc."""
    if doc and "strategyChannels" in doc:
        return dict(doc["strategyChannels"])
    return {}


@router.get("/strategy-channels", response_model=StrategyNotificationsResponse)
async def get_strategy_channels(
    current_user: dict = Depends(get_current_user),
) -> StrategyNotificationsResponse:
    db = get_db()
    user_id = str(current_user["_id"])
    doc = await db.user_settings.find_one({"userId": user_id, "type": "strategy_notifications"})
    enabled_set = _get_user_enabled_set(user_id, doc)
    channels = _get_strategy_channels(doc)

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
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
    channels = _get_strategy_channels(doc)

    if payload.telegramChannelId:
        channels[payload.key] = payload.telegramChannelId.strip()
    else:
        channels.pop(payload.key, None)  # clear → fall back to global default

    await db.user_settings.update_one(
        {"userId": user_id, "type": "strategy_notifications"},
        {"$set": {"strategyChannels": channels}},
        upsert=True,
    )

    items = [
        StrategyNotificationItem(
            key=s.value,
            label=STRATEGY_DISPLAY_NAMES.get(s.value, s.value),
            enabled=s.value in enabled_set,
            telegramChannelId=channels.get(s.value),
        )
        for s in StrategyName
    ]
    return StrategyNotificationsResponse(strategies=items)
