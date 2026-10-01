import { apiClient } from "./client";
import {
  BrokerFunds,
  BrokerOrder,
  ExecuteOrderResult,
  OrderType,
  PortfolioSummary,
  Position,
  Segment,
  Side,
  Trade,
  TradeNotification,
  TradeSizingResult,
} from "@/types";

export interface PlaceTradePayload {
  symbol: string;
  segment: Segment;
  side: Side;
  qty: number;
  orderType: OrderType;
  limitPrice?: number;
}

export interface TradeSizingPayload {
  symbol: string;
  stockPrice: number;
  tightSl: number;
  broker?: string;
  capitalAllocationPct?: number;
  maxRiskPerTrade?: number;
  slBufferPct?: number;
  side?: string;
}

export interface ExecuteOrderPayload {
  symbol: string;
  stockPrice: number;
  tightSl: number;
  qty?: number;
  broker?: string;
  capitalAllocationPct?: number;
  maxRiskPerTrade?: number;
  slBufferPct?: number;
  strategy?: string;
}

export interface ExitPositionPayload {
  symbol: string;
  broker?: string;
  strategy?: string;
}

export const tradingApi = {
  placeTrade: (payload: PlaceTradePayload) => apiClient.post<Trade>("/trades", payload),
  listTrades: () => apiClient.get<Trade[]>("/trades"),
  positions: (segment?: Segment, broker?: string, date?: string | null) => {
    const params: Record<string, string> = {};
    if (segment) params.segment = segment;
    if (broker) params.broker = broker;
    if (date) params.date = date;
    return apiClient.get<Position[]>("/positions", Object.keys(params).length ? params : undefined);
  },
  portfolioSummary: (segment?: Segment, broker?: string, date?: string | null) => {
    const params: Record<string, string> = {};
    if (segment) params.segment = segment;
    if (broker) params.broker = broker;
    if (date) params.date = date;
    return apiClient.get<PortfolioSummary>("/portfolio/summary", Object.keys(params).length ? params : undefined);
  },
  getFunds: (broker: string = "paper", date?: string | null) => {
    const params: Record<string, string> = { broker };
    if (date) params.date = date;
    return apiClient.get<BrokerFunds>("/trades/funds", params);
  },
  calculateSize: (payload: TradeSizingPayload) => apiClient.post<TradeSizingResult>("/trades/calculate-size", payload),
  executeOrder: (payload: ExecuteOrderPayload) => apiClient.post<ExecuteOrderResult>("/trades/execute", payload),
  listOrders: (broker: string = "paper", date?: string | null) => {
    const params: Record<string, string> = { broker };
    if (date) params.date = date;
    return apiClient.get<BrokerOrder[]>("/trades/orders", params);
  },
  cancelOrder: (orderId: string, broker: string = "paper") =>
    apiClient.post<{ success: boolean; orderId: string }>(`/trades/orders/${orderId}/cancel`, undefined, {
      query: { broker },
    }),
  exitPosition: (payload: ExitPositionPayload) => apiClient.post<BrokerOrder>("/trades/positions/exit", payload),
  resetPaperAccount: () => apiClient.post<{ status: string; message: string }>("/trades/paper/reset"),
  getTradeNotifications: () => apiClient.get<TradeNotification[]>("/trades/notifications"),
  markNotificationsRead: () => apiClient.post<{ status: string }>("/trades/notifications/mark-read"),
};
