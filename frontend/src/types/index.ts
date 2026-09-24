export interface User {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string | null;
  createdAt: string;
  lastLoginAt: string;
}

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
  user: User;
}

export interface StockSummary {
  symbol: string;
  name: string;
  exchange: string;
}

export interface Quote {
  symbol: string;
  name: string;
  exchange: string;
  ltp: number;
  change: number;
  changePercent: number;
  open: number;
  high: number;
  low: number;
  prevClose: number;
  volume: number;
  lastUpdated: string;
}

export interface Fundamentals {
  symbol: string;
  marketCap: number;
  peRatio: number;
  pbRatio: number;
  eps: number;
  week52High: number;
  week52Low: number;
  dividendYield: number;
}

export interface StockDetails {
  symbol: string;
  updatedAt: string;
  source: "yahoo" | "cache" | "mock" | "snapshot";
  profile: {
    shortName: string | null;
    sector: string | null;
    sectorDisp: string | null;
    industry: string | null;
    industryDisp: string | null;
  };
  price: {
    regularMarketPrice: number | null;
    previousClose: number | null;
    open: number | null;
    dayLow: number | null;
    dayHigh: number | null;
    regularMarketChange: number | null;
    regularMarketChangePercent: number | null;
    fiftyTwoWeekLow: number | null;
    fiftyTwoWeekHigh: number | null;
    allTimeLow: number | null;
    allTimeHigh: number | null;
    fiftyDayAverage: number | null;
    twoHundredDayAverage: number | null;
    twoHundredDayAverageChange: number | null;
    twoHundredDayAverageChangePercent: number | null;
  };
  valuation: {
    trailingPE: number | null;
    forwardPE: number | null;
    pegRatio: number | null;
    trailingPegRatio: number | null;
    priceToBook: number | null;
    priceToSalesTrailing12Months: number | null;
    priceEpsCurrentYear: number | null;
    beta: number | null;
  };
  market: {
    marketCap: number | null;
    nonDilutedMarketCap: number | null;
    volume: number | null;
    averageVolume: number | null;
    averageVolume10days: number | null;
  };
  profitability: {
    profitMargins: number | null;
    operatingMargins: number | null;
    returnOnEquity: number | null;
    returnOnAssets: number | null;
    trailingEps: number | null;
    revenuePerShare: number | null;
    revenueGrowth: number | null;
  };
  balance: {
    totalCash: number | null;
    totalCashPerShare: number | null;
    totalDebt: number | null;
    totalRevenue: number | null;
    operatingCashflow: number | null;
    quickRatio: number | null;
  };
  dividend: {
    dividendRate: number | null;
    dividendYield: number | null;
  };
  analyst: {
    numberOfAnalystOpinions: number | null;
    recommendationKey: string | null;
    recommendationMean: number | null;
    targetLowPrice: number | null;
    targetHighPrice: number | null;
    targetMeanPrice: number | null;
    targetMedianPrice: number | null;
  };
}

export interface SupportResistanceSet {
  method: string;
  timeframe: string;
  pivot: number;
  r1: number;
  r2: number;
  r3: number | null;
  s1: number;
  s2: number;
  s3: number | null;
}

export interface SwingZone {
  level: number;
  touchCount: number;
  lastTouchedAt: string;
}

export interface SupportLevelsResponse {
  symbol: string;
  computedAt: string;
  pivotMethods: SupportResistanceSet[];
  swingLowZones: SwingZone[];
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  interval: string;
  period: string;
  candles: Candle[];
  fetchedAt: string;
}

export type IntradayTrend = "up" | "down" | "flat";

export interface TradeSetup {
  action: "buy" | "sell";
  status: "waiting" | "pending_entry" | "triggered" | "sl_hit";
  bias: "bullish" | "bearish" | "neutral";
  entry: number;
  stopLoss: number;
  target: number;
  riskRewardRatio: number;
  vwapPosition: "above" | "below" | "at";
  rationale: string;
  triggeredAt: string | null;
  slHitAt: string | null;
  strategy: string;
  conviction: string | null;
  gapClass: string | null;
  confirmation: string | null;
  slWide: number | null;
  triggerPrice: number | null;
  entryMode?: "touch" | "close" | null;
  includeFirstCandle?: boolean | null;
  indexConfluence?: "aligned" | "relative_strength" | "neutral" | null;
  sizingMultiplier?: number | null;
  maxFavorablePrice?: number | null;
  maxFavorableDelta?: number | null;
  maxFavorablePercent?: number | null;
  maxFavorableR?: number | null;
  maxFavorableTime?: string | null;
  stage?: number | null;
  stageKey?: "wait_orb" | "bo_wait_pb" | "pb_forming" | "support_formed" | "triggered" | "sl_hit" | null;
  stageLabel?: string | null;
  stageDesc?: string | null;
}

export interface IntradaySnapshot {
  symbol: string;
  currentPrice: number;
  openingRangeHigh: number;
  openingRangeLow: number;
  openingRangeClose: number;
  swingHighAt: string | null;
  swingLowAt: string | null;
  swingComplete: boolean;
  vwap: number;
  dayHigh: number;
  dayLow: number;
  trend: IntradayTrend;
  candleCount: number;
  tradeSetup: TradeSetup | null;
  updatedAt: string;
  retestDate?: string | null;
  prevClose?: number | null;
  changePercent?: number | null;
}

export interface IntradaySnapshotsResponse {
  snapshots: Record<string, IntradaySnapshot | null>;
  fetchedAt: string;
}

export interface WatchlistItem {
  symbol: string;
  exchange: string;
  addedAt: string;
  ltp: number | null;
  changePercent: number | null;
  nearestSupport: number | null;
  distanceToSupportPercent: number | null;
  belowAllSupports: boolean;
}

export interface Watchlist {
  id: string;
  userId: string;
  name: string;
  sortPreference: "proximity" | "alphabetical" | "dayChange" | "custom";
  strategy: string;
  createdAt: string;
  updatedAt: string;
  items: WatchlistItem[];
}

export type ThresholdType = "percent" | "absolute";
export type AlertChannel = "push" | "email";

export interface Alert {
  id: string;
  userId: string;
  symbol: string;
  method: string;
  levelKey: string;
  levelValueAtCreation: number;
  thresholdType: ThresholdType;
  thresholdValue: number;
  channels: AlertChannel[];
  isActive: boolean;
  lastTriggeredAt: string | null;
  createdAt: string;
  currentPrice: number | null;
  currentDistancePercent: number | null;
}

export type Segment = "intraday" | "delivery";
export type Side = "buy" | "sell";
export type OrderType = "market" | "limit";
export type OrderStatus = "open" | "filled" | "squaredOff" | "cancelled";

export interface Trade {
  id: string;
  userId: string;
  symbol: string;
  segment: Segment;
  side: Side;
  qty: number;
  price: number;
  orderType: OrderType;
  status: OrderStatus;
  executedAt: string;
}

export interface Position {
  symbol: string;
  segment: Segment;
  netQty: number;
  avgPrice: number;
  ltp: number;
  currentValue: number;
  investedValue: number;
  pnl: number;
  pnlPercent: number;
  dayChangePercent: number;
  lastUpdated: string;
  firstBoughtAt: string | null;
  lastTransactionAt: string | null;
}

export interface PortfolioSummary {
  segment: string;
  investedValue: number;
  currentValue: number;
  pnl: number;
  pnlPercent: number;
  todayPnl: number;
  holdingsCount: number;
}
