import { create } from "zustand";
import { authApi } from "@/api/auth";
import { tokenStorage } from "@/api/tokenStorage";
import { User } from "@/types";

interface AuthState {
  user: User | null;
  status: "loading" | "authenticated" | "unauthenticated";
  hydrate: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  loginWithDevAccount: (name: string, email: string) => Promise<void>;
  loginWithGoogle: (idToken: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "loading",

  hydrate: async () => {
    const token = await tokenStorage.getAccessToken();
    if (!token) {
      set({ status: "unauthenticated", user: null });
      return;
    }
    try {
      const user = await authApi.me();
      set({ status: "authenticated", user });
    } catch {
      await tokenStorage.clear();
      set({ status: "unauthenticated", user: null });
    }
  },

  login: async (username, password) => {
    const result = await authApi.login(username, password);
    await tokenStorage.setTokens(result.accessToken, result.refreshToken);
    set({ status: "authenticated", user: result.user });
  },

  loginWithDevAccount: async (name, email) => {
    const result = await authApi.devLogin(name, email);
    await tokenStorage.setTokens(result.accessToken, result.refreshToken);
    set({ status: "authenticated", user: result.user });
  },

  loginWithGoogle: async (idToken) => {
    const result = await authApi.googleLogin(idToken);
    await tokenStorage.setTokens(result.accessToken, result.refreshToken);
    set({ status: "authenticated", user: result.user });
  },

  logout: async () => {
    await tokenStorage.clear();
    set({ status: "unauthenticated", user: null });
  },
}));
