import React, { useState } from "react";
import { View } from "react-native";
import { useRouter } from "expo-router";
import { Button, Card, Screen, Text } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { colors, spacing } from "@/theme/tokens";

export default function LoginScreen() {
  const loginWithDevAccount = useAuthStore((s) => s.loginWithDevAccount);
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDevLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      await loginWithDevAccount("Demo User", "demo@pivotiq.dev");
      router.replace("/(tabs)/search");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen scroll={false} width="narrow">
      <View style={{ flex: 1, justifyContent: "center", gap: spacing.xxl }}>
        <View style={{ alignItems: "center", gap: spacing.md }}>
          <View
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              backgroundColor: colors.accentMuted,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Text variant="display" tone="accent" style={{ fontSize: 30 }}>
              P
            </Text>
          </View>
          <Text variant="display">PivotIQ</Text>
          <Text variant="body" tone="secondary" style={{ textAlign: "center" }}>
            Watchlists, support-level alerts, and paper trading — all in one place.
          </Text>
        </View>

        <Card elevated style={{ gap: spacing.lg }}>
          <View style={{ gap: spacing.xs }}>
            <Text variant="title">Sign in</Text>
            <Text variant="caption" tone="secondary">
              Choose how you want to continue.
            </Text>
          </View>
          <Button label="Continue with Google" variant="secondary" fullWidth disabled />
          <Text variant="caption" tone="muted" style={{ textAlign: "center" }}>
            Google Sign-In requires an OAuth client ID. Use demo access below.
          </Text>
          <Button label="Continue as demo user" onPress={handleDevLogin} loading={loading} fullWidth />
          {error ? (
            <Text variant="caption" tone="negative">
              {error}
            </Text>
          ) : null}
        </Card>

        <Text variant="caption" tone="muted" style={{ textAlign: "center" }}>
          Paper trading only. No real money, no real order routing.
        </Text>
      </View>
    </Screen>
  );
}
