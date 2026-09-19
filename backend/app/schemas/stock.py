from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StockSummary(BaseModel):
    symbol: str
    name: str
    exchange: str


class Quote(BaseModel):
    symbol: str
    name: str
    exchange: str
    ltp: float
    change: float
    changePercent: float
    open: float
    high: float
    low: float
    prevClose: float
    volume: int
    lastUpdated: datetime


class Fundamentals(BaseModel):
    symbol: str
    marketCap: float
    peRatio: float
    pbRatio: float
    eps: float
    week52High: float
    week52Low: float
    dividendYield: float


class SupportResistanceSet(BaseModel):
    method: str
    timeframe: str
    pivot: float
    r1: float
    r2: float
    r3: float | None = None
    s1: float
    s2: float
    s3: float | None = None


class SwingZone(BaseModel):
    level: float
    touchCount: int
    lastTouchedAt: datetime


class SupportLevelsResponse(BaseModel):
    symbol: str
    computedAt: datetime
    pivotMethods: list[SupportResistanceSet]
    swingLowZones: list[SwingZone]


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class CandlesResponse(BaseModel):
    symbol: str
    interval: str
    period: str
    candles: list[Candle]
    fetchedAt: datetime


class TradeSetup(BaseModel):
    action: Literal["buy", "sell"]
    status: Literal["waiting", "pending_entry", "triggered", "sl_hit"] = "waiting"
    bias: Literal["bullish", "bearish", "neutral"]
    entry: float
    stopLoss: float
    target: float
    riskRewardRatio: float
    vwapPosition: Literal["above", "below", "at"]
    rationale: str
    triggeredAt: datetime | None = None
    slHitAt: datetime | None = None
    strategy: str = "orb_vwap"
    conviction: str | None = None
    gapClass: str | None = None
    confirmation: str | None = None
    slWide: float | None = None
    triggerPrice: float | None = None


class IntradaySnapshot(BaseModel):
    symbol: str
    currentPrice: float
    openingRangeHigh: float
    openingRangeLow: float
    openingRangeClose: float
    swingHighAt: datetime | None = None
    swingLowAt: datetime | None = None
    swingComplete: bool = False
    vwap: float
    dayHigh: float
    dayLow: float
    trend: Literal["up", "down", "flat"]
    candleCount: int
    tradeSetup: TradeSetup | None = None
    updatedAt: datetime


class IntradaySnapshotsRequest(BaseModel):
    symbols: list[str]
    strategy: str = "orb_vwap"


class IntradaySnapshotsResponse(BaseModel):
    snapshots: dict[str, IntradaySnapshot | None]
    fetchedAt: datetime


# ---------------- Comprehensive stock details (from Yahoo Finance .info) ----------------


class ProfileInfo(BaseModel):
    shortName: str | None = None
    sector: str | None = None
    sectorDisp: str | None = None
    industry: str | None = None
    industryDisp: str | None = None


class PriceInfo(BaseModel):
    regularMarketPrice: float | None = None
    previousClose: float | None = None
    open: float | None = None
    dayLow: float | None = None
    dayHigh: float | None = None
    regularMarketChange: float | None = None
    regularMarketChangePercent: float | None = None
    fiftyTwoWeekLow: float | None = None
    fiftyTwoWeekHigh: float | None = None
    allTimeLow: float | None = None
    allTimeHigh: float | None = None
    fiftyDayAverage: float | None = None
    twoHundredDayAverage: float | None = None
    twoHundredDayAverageChange: float | None = None
    twoHundredDayAverageChangePercent: float | None = None


class ValuationInfo(BaseModel):
    trailingPE: float | None = None
    forwardPE: float | None = None
    pegRatio: float | None = None
    trailingPegRatio: float | None = None
    priceToBook: float | None = None
    priceToSalesTrailing12Months: float | None = None
    priceEpsCurrentYear: float | None = None
    beta: float | None = None


class MarketInfo(BaseModel):
    marketCap: float | None = None
    nonDilutedMarketCap: float | None = None
    volume: int | None = None
    averageVolume: int | None = None
    averageVolume10days: int | None = None


class ProfitabilityInfo(BaseModel):
    profitMargins: float | None = None
    operatingMargins: float | None = None
    returnOnEquity: float | None = None
    returnOnAssets: float | None = None
    trailingEps: float | None = None
    revenuePerShare: float | None = None
    revenueGrowth: float | None = None


class BalanceInfo(BaseModel):
    totalCash: float | None = None
    totalCashPerShare: float | None = None
    totalDebt: float | None = None
    totalRevenue: float | None = None
    operatingCashflow: float | None = None
    quickRatio: float | None = None


class DividendInfo(BaseModel):
    dividendRate: float | None = None
    dividendYield: float | None = None


class AnalystInfo(BaseModel):
    numberOfAnalystOpinions: int | None = None
    recommendationKey: str | None = None
    recommendationMean: float | None = None
    targetLowPrice: float | None = None
    targetHighPrice: float | None = None
    targetMeanPrice: float | None = None
    targetMedianPrice: float | None = None


class StockDetails(BaseModel):
    symbol: str
    updatedAt: datetime
    source: Literal["yahoo", "cache", "mock", "snapshot"]
    profile: ProfileInfo
    price: PriceInfo
    valuation: ValuationInfo
    market: MarketInfo
    profitability: ProfitabilityInfo
    balance: BalanceInfo
    dividend: DividendInfo
    analyst: AnalystInfo
