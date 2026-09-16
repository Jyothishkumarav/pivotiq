import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

/** Token storage abstraction: SecureStore (Keychain/Keystore) on native,
 * localStorage on web — mirrors the "httpOnly cookie on web" guidance loosely,
 * acceptable for this MVP since the web build isn't behind a cookie-issuing gateway. */
const ACCESS_KEY = "pivotiq.accessToken";
const REFRESH_KEY = "pivotiq.refreshToken";

async function getItem(key: string): Promise<string | null> {
  if (Platform.OS === "web") {
    return typeof localStorage !== "undefined" ? localStorage.getItem(key) : null;
  }
  return SecureStore.getItemAsync(key);
}

async function setItem(key: string, value: string): Promise<void> {
  if (Platform.OS === "web") {
    if (typeof localStorage !== "undefined") localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function deleteItem(key: string): Promise<void> {
  if (Platform.OS === "web") {
    if (typeof localStorage !== "undefined") localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export const tokenStorage = {
  getAccessToken: () => getItem(ACCESS_KEY),
  getRefreshToken: () => getItem(REFRESH_KEY),
  setTokens: async (accessToken: string, refreshToken: string) => {
    await setItem(ACCESS_KEY, accessToken);
    await setItem(REFRESH_KEY, refreshToken);
  },
  setAccessToken: (accessToken: string) => setItem(ACCESS_KEY, accessToken),
  clear: async () => {
    await deleteItem(ACCESS_KEY);
    await deleteItem(REFRESH_KEY);
  },
};
