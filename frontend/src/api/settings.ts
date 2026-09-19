import { apiClient } from "./client";

export type DataSourceMode = "real" | "mock";

interface DataSourceResponse {
  mode: DataSourceMode;
}

export interface StrategyNotificationItem {
  key: string;
  label: string;
  enabled: boolean;
}

export interface StrategyNotificationsResponse {
  strategies: StrategyNotificationItem[];
}

export const settingsApi = {
  getDataSource: () => apiClient.get<DataSourceResponse>("/settings/data-source"),
  setDataSource: (mode: DataSourceMode) => apiClient.put<DataSourceResponse>("/settings/data-source", { mode }),
  getStrategyNotifications: () =>
    apiClient.get<StrategyNotificationsResponse>("/settings/strategy-notifications"),
  updateStrategyNotification: (key: string, enabled: boolean) =>
    apiClient.put<StrategyNotificationsResponse>("/settings/strategy-notifications", { key, enabled }),
};
