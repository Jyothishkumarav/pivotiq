from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ThresholdType(str, Enum):
    percent = "percent"
    absolute = "absolute"


class AlertChannel(str, Enum):
    push = "push"
    email = "email"


class AlertCreate(BaseModel):
    symbol: str
    method: str
    levelKey: str
    thresholdType: ThresholdType
    thresholdValue: float
    channels: list[AlertChannel] = [AlertChannel.push]


class AlertUpdate(BaseModel):
    thresholdType: ThresholdType | None = None
    thresholdValue: float | None = None
    channels: list[AlertChannel] | None = None
    isActive: bool | None = None


class AlertOut(BaseModel):
    id: str
    userId: str
    symbol: str
    method: str
    levelKey: str
    levelValueAtCreation: float
    thresholdType: ThresholdType
    thresholdValue: float
    channels: list[AlertChannel]
    isActive: bool
    lastTriggeredAt: datetime | None = None
    createdAt: datetime
    currentPrice: float | None = None
    currentDistancePercent: float | None = None
