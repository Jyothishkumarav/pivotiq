from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Segment(str, Enum):
    intraday = "intraday"
    delivery = "delivery"


class Side(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"
    sl_m = "sl_m"
    sl_l = "sl_l"


class OrderStatus(str, Enum):
    open = "open"
    filled = "filled"
    squaredOff = "squaredOff"
    cancelled = "cancelled"
    rejected = "rejected"


class TradeCreate(BaseModel):
    symbol: str
    segment: Segment
    side: Side
    qty: int = Field(gt=0)
    orderType: OrderType = OrderType.market
    limitPrice: float | None = None


class TradeOut(BaseModel):
    id: str
    userId: str
    symbol: str
    segment: Segment
    side: Side
    qty: int
    price: float
    orderType: OrderType
    status: OrderStatus
    executedAt: datetime


class PositionOut(BaseModel):
    symbol: str
    segment: Segment
    netQty: int
    avgPrice: float
    ltp: float
    currentValue: float
    investedValue: float
    pnl: float
    pnlPercent: float
    dayChangePercent: float
    lastUpdated: datetime
    firstBoughtAt: datetime | None = None
    lastTransactionAt: datetime | None = None
    side: str | None = None
    stopLoss: float | None = None
    bufferedStopLoss: float | None = None
    strategyStopLoss: float | None = None
    fyersUrl: str | None = None


class TradeNotificationOut(BaseModel):
    id: str
    symbol: str
    fyersSymbol: str
    fyersUrl: str
    side: str
    qty: int
    entryPrice: float
    stopLoss: float
    strategy: str | None = None
    time: datetime
    status: str
    message: str
    read: bool = False


class PortfolioSummary(BaseModel):
    segment: str
    investedValue: float
    currentValue: float
    pnl: float
    pnlPercent: float
    todayPnl: float
    holdingsCount: int

