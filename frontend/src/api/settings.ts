import { apiClient } from "./client";

export type DataSourceMode = "real" | "mock";

interface DataSourceResponse {
  mode: DataSourceMode;
}

export const settingsApi = {
  getDataSource: () => apiClient.get<DataSourceResponse>("/settings/data-source"),
  setDataSource: (mode: DataSourceMode) => apiClient.put<DataSourceResponse>("/settings/data-source", { mode }),
};
