import { apiClient } from "./client";
import { Alert, AlertChannel, ThresholdType } from "@/types";

export interface CreateAlertPayload {
  symbol: string;
  method: string;
  levelKey: string;
  thresholdType: ThresholdType;
  thresholdValue: number;
  channels: AlertChannel[];
}

export const alertsApi = {
  list: () => apiClient.get<Alert[]>("/alerts"),
  create: (payload: CreateAlertPayload) => apiClient.post<Alert>("/alerts", payload),
  update: (id: string, payload: Partial<CreateAlertPayload & { isActive: boolean }>) =>
    apiClient.put<Alert>(`/alerts/${id}`, payload),
  remove: (id: string) => apiClient.delete<void>(`/alerts/${id}`),
};
