import React from "react";
import { Modal, Platform, Pressable, Switch, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Text } from "@/components/ui";
import { settingsApi, StrategyNotificationItem } from "@/api/settings";
import { colors, radius, spacing } from "@/theme/tokens";

interface Props {
  visible: boolean;
  onClose: () => void;
}

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  orb_vwap: "Enters on initial ORB breakout aligned with VWAP.",
  context_gated: "Filters breakouts using market gap bias, trend, and HL-BOS structure.",
  orb_pullback: "Waits for pullback to complete, enters on break of pullback high/low.",
  orb_pullback_support: "Early entry on break of the first supporting reversal candle.",
};

const STRATEGY_BADGES: Record<string, { glyph: string; color: string }> = {
  orb_vwap: { glyph: "⚡", color: "#5B8BFF" },
  context_gated: { glyph: "🛡️", color: "#9AA9C7" },
  orb_pullback: { glyph: "🔄", color: "#F5B54A" },
  orb_pullback_support: { glyph: "🎯", color: "#3DDB9F" },
};

export function StrategyAlertsModal({ visible, onClose }: Props) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["strategy-notifications"],
    queryFn: settingsApi.getStrategyNotifications,
    enabled: visible,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
      settingsApi.updateStrategyNotification(key, enabled),
    onMutate: async ({ key, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ["strategy-notifications"] });
      const prev = queryClient.getQueryData<{ strategies: StrategyNotificationItem[] }>([
        "strategy-notifications",
      ]);
      if (prev) {
        queryClient.setQueryData(["strategy-notifications"], {
          strategies: prev.strategies.map((s) =>
            s.key === key ? { ...s, enabled } : s
          ),
        });
      }
      return { prev };
    },
    onError: (_err, _vars, context) => {
      if (context?.prev) {
        queryClient.setQueryData(["strategy-notifications"], context.prev);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-notifications"] });
    },
  });

  const strategies = data?.strategies ?? [];
  const enabledCount = strategies.filter((s) => s.enabled).length;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable
        onPress={onClose}
        style={{
          flex: 1,
          backgroundColor: colors.overlay,
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.md,
        }}
      >
        <Pressable
          onPress={(e) => e.stopPropagation()}
          style={{
            width: "100%",
            maxWidth: 540,
            backgroundColor: colors.surface,
            borderRadius: radius.lg,
            borderWidth: 1,
            borderColor: colors.border,
            padding: spacing.xl,
            gap: spacing.lg,
            ...(Platform.OS === "web"
              ? ({ boxShadow: "0 12px 40px rgba(0,0,0,0.5)" } as any)
              : {}),
          }}
        >
          {/* Header */}
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
            <View style={{ gap: 4, flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Text variant="title">Strategy Notifications</Text>
                <Badge label="Telegram" tone="neutral" />
              </View>
              <Text variant="caption" tone="secondary">
                Control which strategies fire automated alerts to your connected Telegram channel.
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              style={({ hovered }: any) => ({
                width: 32,
                height: 32,
                borderRadius: 999,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: hovered ? colors.surfaceElevated : "transparent",
              })}
            >
              <Text style={{ fontSize: 18, color: colors.textSecondary, lineHeight: 22 }}>✕</Text>
            </Pressable>
          </View>

          {/* Status summary */}
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              alignItems: "center",
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              backgroundColor: colors.surfaceElevated,
              borderRadius: radius.md,
              borderWidth: 1,
              borderColor: colors.borderSubtle,
            }}
          >
            <Text variant="caption" tone="muted">
              {enabledCount} of {strategies.length} strategies active
            </Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable
                onPress={() => {
                  strategies.forEach((s) => {
                    if (!s.enabled) toggleMutation.mutate({ key: s.key, enabled: true });
                  });
                }}
              >
                <Text variant="caption" tone="accent">Enable all</Text>
              </Pressable>
              <Text variant="caption" tone="muted">·</Text>
              <Pressable
                onPress={() => {
                  strategies.forEach((s) => {
                    if (s.enabled) toggleMutation.mutate({ key: s.key, enabled: false });
                  });
                }}
              >
                <Text variant="caption" tone="muted">Mute all</Text>
              </Pressable>
            </View>
          </View>

          {/* Strategy List */}
          {isLoading && strategies.length === 0 ? (
            <LoadingBlock label="Loading strategy settings…" compact />
          ) : (
            <View style={{ gap: spacing.sm }}>
              {strategies.map((strat) => {
                const badge = STRATEGY_BADGES[strat.key] ?? { glyph: "📈", color: colors.accent };
                const desc = STRATEGY_DESCRIPTIONS[strat.key] ?? "";
                return (
                  <View
                    key={strat.key}
                    style={{
                      flexDirection: "row",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: spacing.md,
                      borderRadius: radius.md,
                      borderWidth: 1,
                      borderColor: strat.enabled ? colors.border : colors.borderSubtle,
                      backgroundColor: strat.enabled ? `${colors.surfaceElevated}` : "transparent",
                    }}
                  >
                    <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, flex: 1, paddingRight: spacing.md }}>
                      <View
                        style={{
                          width: 36,
                          height: 36,
                          borderRadius: 8,
                          alignItems: "center",
                          justifyContent: "center",
                          backgroundColor: `${badge.color}15`,
                          borderWidth: 1,
                          borderColor: `${badge.color}35`,
                        }}
                      >
                        <Text style={{ fontSize: 16 }}>{badge.glyph}</Text>
                      </View>
                      <View style={{ flex: 1, gap: 2 }}>
                        <Text variant="bodyStrong">{strat.label}</Text>
                        {desc ? (
                          <Text variant="caption" tone="muted" numberOfLines={2}>
                            {desc}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                    <Switch
                      value={strat.enabled}
                      onValueChange={(val) => toggleMutation.mutate({ key: strat.key, enabled: val })}
                      trackColor={{ false: colors.borderSubtle, true: colors.positive }}
                      thumbColor={strat.enabled ? "#FFFFFF" : colors.textSecondary}
                    />
                  </View>
                );
              })}
            </View>
          )}

          {/* Footer */}
          <View style={{ flexDirection: "row", justifyContent: "flex-end" }}>
            <Button label="Done" size="sm" onPress={onClose} />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
