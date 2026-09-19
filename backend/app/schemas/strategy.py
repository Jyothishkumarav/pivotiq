from enum import Enum
from pydantic import BaseModel


class StrategyName(str, Enum):
    ORB_VWAP = "orb_vwap"
    CONTEXT_GATED = "context_gated"
    ORB_PULLBACK = "orb_pullback"
    ORB_PULLBACK_SUPPORT = "orb_pullback_support"


STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    StrategyName.ORB_VWAP.value: "ORB + VWAP (default)",
    StrategyName.CONTEXT_GATED.value: "Context-gated (gap/trend/HL-BOS)",
    StrategyName.ORB_PULLBACK.value: "ORB + VWAP Pullback",
    StrategyName.ORB_PULLBACK_SUPPORT.value: "ORB + Pullback Support",
}

STRATEGY_SHORT_NAMES: dict[str, str] = {
    StrategyName.ORB_VWAP.value: "ORB + VWAP",
    StrategyName.CONTEXT_GATED.value: "Context-gated",
    StrategyName.ORB_PULLBACK.value: "ORB + VWAP Pullback",
    StrategyName.ORB_PULLBACK_SUPPORT.value: "ORB + Pullback Support",
}


class StrategyNotificationItem(BaseModel):
    key: str
    label: str
    enabled: bool


class StrategyNotificationsResponse(BaseModel):
    strategies: list[StrategyNotificationItem]


class StrategyNotificationUpdate(BaseModel):
    key: str
    enabled: bool
