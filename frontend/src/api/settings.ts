import { apiClient } from "./client";

export type DataSourceMode = "real" | "mock";

interface DataSourceResponse {
  mode: DataSourceMode;
}

export interface TelegramChannelOption {
  id: string;
  name: string;
}

export interface StrategyNotificationItem {
  key: string;
  label: string;
  enabled: boolean;
  telegramChannelId?: string | null;
  telegramChannelName?: string | null;
}

export interface StrategyNotificationsResponse {
  strategies: StrategyNotificationItem[];
  availableChannels?: TelegramChannelOption[];
}

export interface WatchlistOption {
  id: string;
  name: string;
  itemCount: number;
}

export interface TradingSettingsResponse {
  paperCapital: number;
  slBufferPct: number;
  maxRiskPerTrade: number;
  maxOpenPositions: number;
  activeWatchlistId: string | null;
  availableWatchlists: WatchlistOption[];
}

export interface TradingSettingsUpdate {
  paperCapital?: number;
  slBufferPct?: number;
  maxRiskPerTrade?: number;
  maxOpenPositions?: number;
  activeWatchlistId?: string | null;
}

export const settingsApi = {
  getDataSource: () => apiClient.get<DataSourceResponse>("/settings/data-source"),
  setDataSource: (mode: DataSourceMode) => apiClient.put<DataSourceResponse>("/settings/data-source", { mode }),
  getStrategyNotifications: () =>
    apiClient.get<StrategyNotificationsResponse>("/settings/strategy-notifications"),
  updateStrategyNotification: (key: string, enabled: boolean) =>
    apiClient.put<StrategyNotificationsResponse>("/settings/strategy-notifications", { key, enabled }),
  getStrategyChannels: () =>
    apiClient.get<StrategyNotificationsResponse>("/settings/strategy-channels"),
  updateStrategyChannel: (key: string, telegramChannelId: string | null, telegramChannelName?: string | null) =>
    apiClient.put<StrategyNotificationsResponse>("/settings/strategy-channels", {
      key,
      telegramChannelId,
      telegramChannelName,
    }),
  getStrategyAutoTrade: () =>
    apiClient.get<import("@/types").StrategyAutoTradeResponse>("/settings/strategy-autotrade"),
  updateStrategyAutoTrade: (payload: import("@/types").StrategyAutoTradeUpdate) =>
    apiClient.put<import("@/types").StrategyAutoTradeResponse>("/settings/strategy-autotrade", payload),
  getTradingSettings: () =>
    apiClient.get<TradingSettingsResponse>("/settings/trading"),
  updateTradingSettings: (payload: TradingSettingsUpdate) =>
    apiClient.put<TradingSettingsResponse>("/settings/trading", payload),
};


