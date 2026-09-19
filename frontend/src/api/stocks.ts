import { apiClient } from "./client";
import {
  CandlesResponse,
  Fundamentals,
  IntradaySnapshot,
  IntradaySnapshotsResponse,
  Quote,
  StockDetails,
  StockSummary,
  SupportLevelsResponse,
} from "@/types";

export const stocksApi = {
  search: (q: string) => apiClient.get<StockSummary[]>("/stocks/search", { q }),
  quote: (symbol: string) => apiClient.get<Quote>(`/stocks/${symbol}/quote`),
  fundamentals: (symbol: string) => apiClient.get<Fundamentals>(`/stocks/${symbol}/fundamentals`),
  details: (symbol: string, refresh = false) =>
    apiClient.get<StockDetails>(`/stocks/${symbol}/details`, refresh ? { refresh: "true" } : undefined),
  supportLevels: (symbol: string) => apiClient.get<SupportLevelsResponse>(`/stocks/${symbol}/support-levels`),
  candles: (symbol: string, period = "1y", interval = "1d") =>
    apiClient.get<CandlesResponse>(`/stocks/${symbol}/candles`, { period, interval }),
  intradaySnapshot: (symbol: string, strategy = "orb_vwap", entryMode: "touch" | "close" = "close", retestDate?: string | null) =>
    apiClient.get<IntradaySnapshot>(`/stocks/${symbol}/intraday-snapshot`, {
      strategy,
      entry_mode: entryMode,
      ...(retestDate ? { retest_date: retestDate } : {}),
    }),
  intradaySnapshots: (symbols: string[], strategy = "orb_vwap", entryMode: "touch" | "close" = "close", retestDate?: string | null) =>
    apiClient.post<IntradaySnapshotsResponse>("/stocks/intraday-snapshots", {
      symbols,
      strategy,
      entryMode,
      ...(retestDate ? { retestDate } : {}),
    }),
  clearFrozenTriggers: (strategy: string, symbols?: string[], date?: string) =>
    apiClient.delete<{ deleted: number; message: string }>("/stocks/intraday-triggers", {
      strategy,
      ...(symbols ? { symbols } : {}),
      ...(date ? { date } : {}),
    }),
};
