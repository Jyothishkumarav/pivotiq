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
};

