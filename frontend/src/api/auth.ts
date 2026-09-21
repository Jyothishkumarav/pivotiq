import { apiClient } from "./client";
import { TokenPair, User } from "@/types";

export const authApi = {
  login: (username: string, password: string) =>
    apiClient.post<TokenPair>("/auth/login", { username, password }, { auth: false }),
  devLogin: (name: string, email: string) =>
    apiClient.post<TokenPair>("/auth/dev-login", { name, email }, { auth: false }),
  googleLogin: (idToken: string) => apiClient.post<TokenPair>("/auth/google", { idToken }, { auth: false }),
  me: () => apiClient.get<User>("/auth/me"),
  logoutAllDevices: () => apiClient.post<void>("/auth/logout-all"),
};
