from datetime import datetime

from pydantic import BaseModel, Field


class WatchlistItemIn(BaseModel):
    symbol: str
    exchange: str = "NSE"
    autoTrade: bool = False


class WatchlistItemOut(BaseModel):
    symbol: str
    exchange: str
    addedAt: datetime
    autoTrade: bool = False
    ltp: float | None = None
    changePercent: float | None = None
    nearestSupport: float | None = None
    distanceToSupportPercent: float | None = None
    belowAllSupports: bool = False


class WatchlistItemAutoTradeUpdate(BaseModel):
    autoTrade: bool


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class WatchlistRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class WatchlistReorder(BaseModel):
    symbols: list[str]


class WatchlistOut(BaseModel):
    id: str
    userId: str
    name: str
    sortPreference: str = "alphabetical"
    strategy: str = "orb_vwap"
    createdAt: datetime
    updatedAt: datetime
    items: list[WatchlistItemOut] = []
