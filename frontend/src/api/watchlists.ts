import { apiClient } from "./client";
import { Watchlist } from "@/types";

export const watchlistsApi = {
  list: () => apiClient.get<Watchlist[]>("/watchlists"),
  create: (name: string) => apiClient.post<Watchlist>("/watchlists", { name }),
  rename: (id: string, name: string) => apiClient.put<Watchlist>(`/watchlists/${id}`, { name }),
  remove: (id: string) => apiClient.delete<void>(`/watchlists/${id}`),
  addItem: (id: string, symbol: string, exchange = "NSE") =>
    apiClient.post<Watchlist>(`/watchlists/${id}/items`, { symbol, exchange }),
  removeItem: (id: string, symbol: string) => apiClient.delete<Watchlist>(`/watchlists/${id}/items/${symbol}`),
  reorder: (id: string, symbols: string[]) => apiClient.put<Watchlist>(`/watchlists/${id}/reorder`, { symbols }),
  setSortPreference: (id: string, preference: string) =>
    apiClient.put<Watchlist>(`/watchlists/${id}/sort-preference?preference=${preference}`),
  setStrategy: (id: string, strategy: string) =>
    apiClient.put<Watchlist>(`/watchlists/${id}/strategy?strategy=${strategy}`),
};
