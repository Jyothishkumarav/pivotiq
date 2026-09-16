import { apiClient } from "./client";

export interface FyersLoginUrl {
  url: string;
  state: string;
}

export interface FyersStatus {
  connected: boolean;
  connectedAt: string | null;
  expiresAt: string | null;
  profileName: string | null;
}

export const fyersApi = {
  authUrl: () => apiClient.get<FyersLoginUrl>("/fyers/auth-url"),
  exchangeCode: (authCode: string, state?: string) =>
    apiClient.post<FyersStatus>("/fyers/exchange-code", { authCode, state }),
  status: () => apiClient.get<FyersStatus>("/fyers/status"),
  disconnect: () => apiClient.post<void>("/fyers/disconnect"),
};
