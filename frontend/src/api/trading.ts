import { apiClient } from "./client";
import { OrderType, PortfolioSummary, Position, Segment, Side, Trade } from "@/types";

export interface PlaceTradePayload {
  symbol: string;
  segment: Segment;
  side: Side;
  qty: number;
  orderType: OrderType;
  limitPrice?: number;
}

export const tradingApi = {
  placeTrade: (payload: PlaceTradePayload) => apiClient.post<Trade>("/trades", payload),
  listTrades: () => apiClient.get<Trade[]>("/trades"),
  positions: (segment?: Segment) => apiClient.get<Position[]>("/positions", segment ? { segment } : undefined),
  portfolioSummary: (segment?: Segment) =>
    apiClient.get<PortfolioSummary>("/portfolio/summary", segment ? { segment } : undefined),
};
