from enum import Enum
from pydantic import BaseModel


class StrategyName(str, Enum):
    ORB_FLOW = "orb_flow"
    ORB_PULLBACK_SUPPORT = "orb_pullback_support"
    ORB_PULLBACK = "orb_pullback"


STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    StrategyName.ORB_FLOW.value: "ORB Institutional Flow",
    StrategyName.ORB_PULLBACK_SUPPORT.value: "ORB + Pullback Support",
    StrategyName.ORB_PULLBACK.value: "ORB + VWAP Pullback",
    "orb_vwap": "ORB + VWAP",
    "context_gated": "Context-gated",
}

STRATEGY_SHORT_NAMES: dict[str, str] = {
    StrategyName.ORB_FLOW.value: "Institutional Flow",
    StrategyName.ORB_PULLBACK_SUPPORT.value: "ORB + Pullback Support",
    StrategyName.ORB_PULLBACK.value: "ORB + VWAP Pullback",
    "orb_vwap": "ORB + VWAP",
    "context_gated": "Context-gated",
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
