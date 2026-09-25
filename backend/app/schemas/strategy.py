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
    telegramChannelId: str | None = None    # per-strategy Telegram chat/channel ID
    telegramChannelName: str | None = None  # human-readable group/channel title


class TelegramChannelOption(BaseModel):
    id: str
    name: str


class StrategyNotificationsResponse(BaseModel):
    strategies: list[StrategyNotificationItem]
    availableChannels: list[TelegramChannelOption] = []


class StrategyNotificationUpdate(BaseModel):
    key: str
    enabled: bool


class StrategyChannelUpdate(BaseModel):
    key: str
    telegramChannelId: str | None = None    # None = clear / use global default
    telegramChannelName: str | None = None  # optional friendly name override


class StrategyAutoTradeItem(BaseModel):
    key: str
    label: str
    enabled: bool = False
    broker: str = "paper"  # "fyers" | "paper"
    capitalAllocationPct: float = 50.0
    maxRiskPerTrade: float = 1100.0
    slBufferPct: float = 20.0
    leverage: float = 5.0
    productType: str = "INTRADAY"


class StrategyAutoTradeResponse(BaseModel):
    strategies: list[StrategyAutoTradeItem]
    availableBrokers: list[dict[str, str]] = []


class StrategyAutoTradeUpdate(BaseModel):
    key: str
    enabled: bool | None = None
    broker: str | None = None
    capitalAllocationPct: float | None = None
    maxRiskPerTrade: float | None = None
    slBufferPct: float | None = None

