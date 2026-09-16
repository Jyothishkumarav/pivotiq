import React, { useState } from "react";
import { Linking, Platform, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, Text } from "@/components/ui";
import { fyersApi } from "@/api/fyers";
import { colors, spacing } from "@/theme/tokens";

function openExternal(url: string) {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  } else {
    Linking.openURL(url).catch(() => undefined);
  }
}

function ConnectPanel({ onConnected }: { onConnected: () => void }) {
  const [authCode, setAuthCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const authUrlMutation = useMutation({
    mutationFn: fyersApi.authUrl,
    onSuccess: (data) => openExternal(data.url),
    onError: (e) => setError(e instanceof Error ? e.message : "Failed to build login URL"),
  });
  const exchangeMutation = useMutation({
    mutationFn: (code: string) => fyersApi.exchangeCode(code),
    onSuccess: () => {
      setAuthCode("");
      setError(null);
      onConnected();
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Failed to exchange auth code"),
  });

  return (
    <View style={{ gap: spacing.md }}>
      <View style={{ gap: spacing.sm }}>
        <Text variant="caption" tone="muted">
          Step 1
        </Text>
        <Button
          label={authUrlMutation.isPending ? "Opening…" : "Open Fyers login"}
          onPress={() => authUrlMutation.mutate()}
          loading={authUrlMutation.isPending}
          variant="secondary"
        />
        <Text variant="caption" tone="muted">
          Sign in and approve. Fyers redirects you to a page whose URL contains an
          <Text variant="caption" tone="primary"> auth_code</Text>. Copy the value.
        </Text>
      </View>

      <View style={{ gap: spacing.sm }}>
        <Text variant="caption" tone="muted">
          Step 2
        </Text>
        <Input
          placeholder="Paste the auth_code here"
          value={authCode}
          onChangeText={setAuthCode}
          autoCapitalize="none"
        />
        <Button
          label={exchangeMutation.isPending ? "Connecting…" : "Connect"}
          onPress={() => authCode.trim() && exchangeMutation.mutate(authCode.trim())}
          loading={exchangeMutation.isPending}
          disabled={!authCode.trim()}
        />
        {error ? (
          <Text variant="caption" tone="negative">
            {error}
          </Text>
        ) : null}
      </View>

      <Text variant="caption" tone="muted">
        We only use Fyers to fetch live stock prices (LTP + OHLC). No orders are placed and
        your Fyers portfolio is never accessed.
      </Text>
    </View>
  );
}

/** Compact status widget shown at the top of the Portfolio page.
 * Collapsed pill when connected · expandable connect flow when not. */
export function FyersConnectionCard() {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["fyers", "status"],
    queryFn: fyersApi.status,
  });
  const invalidatePriceData = () => {
    queryClient.invalidateQueries({ queryKey: ["fyers"] });
    queryClient.invalidateQueries({ queryKey: ["quote"] });
    queryClient.invalidateQueries({ queryKey: ["positions"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
    queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    queryClient.invalidateQueries({ queryKey: ["candles"] });
  };
  const disconnectMutation = useMutation({
    mutationFn: fyersApi.disconnect,
    onSuccess: invalidatePriceData,
  });

  if (isLoading) return null;

  const connected = !!data?.connected;

  return (
    <Card
      style={{
        gap: spacing.sm,
        borderColor: connected ? colors.positive : colors.borderSubtle,
        borderLeftWidth: 3,
        borderLeftColor: connected ? colors.positive : colors.warning,
      }}
    >
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flex: 1 }}>
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              backgroundColor: connected ? colors.positive : colors.warning,
            }}
          />
          <View style={{ flex: 1 }}>
            <Text variant="bodyStrong">
              {connected ? "Live prices from Fyers" : "Not connected to Fyers"}
            </Text>
            <Text variant="caption" tone="muted">
              {connected
                ? `${data?.profileName ? `${data.profileName} · ` : ""}session valid until ${
                    data?.expiresAt ? new Date(data.expiresAt).toLocaleTimeString() : "next rotation"
                  }`
                : "Fetching LTPs from Yahoo. Connect Fyers for real-time NSE prices."}
            </Text>
          </View>
        </View>
        {connected ? (
          <Button
            label="Disconnect"
            size="sm"
            variant="secondary"
            loading={disconnectMutation.isPending}
            onPress={() => disconnectMutation.mutate()}
          />
        ) : (
          <Button
            label={expanded ? "Close" : "Connect"}
            size="sm"
            onPress={() => setExpanded((v) => !v)}
          />
        )}
      </View>

      {expanded && !connected ? (
        <View
          style={{
            marginTop: spacing.sm,
            paddingTop: spacing.md,
            borderTopWidth: 1,
            borderTopColor: colors.divider,
          }}
        >
          <ConnectPanel
            onConnected={() => {
              setExpanded(false);
              invalidatePriceData();
            }}
          />
        </View>
      ) : null}
    </Card>
  );
}
