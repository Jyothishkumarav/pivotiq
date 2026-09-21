import React, { useEffect } from "react";
import { ActivityIndicator, Platform, View } from "react-native";
import { Stack, useRouter, useSegments } from "expo-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import { useAuthStore } from "@/store/authStore";
import { WebTopNav } from "@/components/WebTopNav";
import { colors } from "@/theme/tokens";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function AuthGate({ children }: { children: React.ReactNode }) {
  const { status, hydrate } = useAuthStore();
  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (status === "loading") return;
    const inAuthGroup = segments[0] === "login";
    if (status === "unauthenticated" && !inAuthGroup) {
      if (Platform.OS === "web" && typeof window !== "undefined") {
        window.location.replace("/login");
      } else {
        router.replace("/login");
      }
    } else if (status === "authenticated" && inAuthGroup) {
      if (Platform.OS === "web" && typeof window !== "undefined") {
        window.location.replace("/(tabs)/search");
      } else {
        router.replace("/(tabs)/search");
      }
    }
  }, [status, segments, router]);

  if (status === "loading") {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background }}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return <>{children}</>;
}

function AppShell({ children }: { children: React.ReactNode }) {
  const { status } = useAuthStore();
  const segments = useSegments();
  const inAuthGroup = segments[0] === "login";
  const showWebNav = Platform.OS === "web" && status === "authenticated" && !inAuthGroup;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {showWebNav ? <WebTopNav /> : null}
      <View style={{ flex: 1 }}>{children}</View>
    </View>
  );
}

export default function RootLayout() {
  const isWeb = Platform.OS === "web";
  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="light" />
      <AuthGate>
        <AppShell>
          <Stack
            screenOptions={{
              headerStyle: { backgroundColor: colors.background },
              headerTintColor: colors.textPrimary,
              headerShadowVisible: false,
              contentStyle: { backgroundColor: colors.background },
              headerShown: !isWeb,
            }}
          >
            <Stack.Screen name="login" options={{ headerShown: false }} />
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="stock/[symbol]" options={{ title: "Stock detail" }} />
            <Stack.Screen name="watchlist/[id]" options={{ title: "Watchlist" }} />
            <Stack.Screen
              name="alert/new"
              options={{ title: "New alert", presentation: "modal", headerShown: true }}
            />
          </Stack>
        </AppShell>
      </AuthGate>
    </QueryClientProvider>
  );
}
