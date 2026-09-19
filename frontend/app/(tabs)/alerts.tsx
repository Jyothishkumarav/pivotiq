import React, { useState } from "react";
import { Platform, Pressable, Switch, useWindowDimensions, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Screen, Text } from "@/components/ui";
import { alertsApi } from "@/api/alerts";
import { settingsApi, StrategyNotificationItem } from "@/api/settings";
import { StrategyAlertsModal } from "@/components/StrategyAlertsModal";
import { colors, radius, spacing } from "@/theme/tokens";
import { formatCurrency, formatPercent } from "@/utils/format";

const STRATEGY_META: Record<string, { glyph: string; color: string; desc: string }> = {
  orb_vwap: {
    glyph: "⚡",
    color: "#5B8BFF",
    desc: "Enters on initial ORB breakout aligned with VWAP slope.",
  },
  context_gated: {
    glyph: "🛡️",
    color: "#9AA9C7",
    desc: "Filters breakouts with gap bias, daily trend, and HL-BOS structure.",
  },
  orb_pullback: {
    glyph: "🔄",
    color: "#F5B54A",
    desc: "Waits for pullback completion, enters on break of pullback high/low.",
  },
  orb_pullback_support: {
    glyph: "🎯",
    color: "#3DDB9F",
    desc: "Early entry on break of first reversal candle after pullback completes.",
  },
};

export default function AlertsScreen() {
  const queryClient = useQueryClient();
  const [showConfigModal, setShowConfigModal] = useState(false);
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === "web" && width >= 768;

  // Price level alerts
  const { data: alerts, isLoading: isAlertsLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: alertsApi.list,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      alertsApi.update(id, { isActive }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => alertsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  // Strategy notifications
  const { data: strategyData, isLoading: isStrategyLoading } = useQuery({
    queryKey: ["strategy-notifications"],
    queryFn: settingsApi.getStrategyNotifications,
  });

  const strategyMutation = useMutation({
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

  const strategies = strategyData?.strategies ?? [];
  const enabledCount = strategies.filter((s) => s.enabled).length;

  return (
    <Screen width="wide">
      <View style={{ gap: spacing.xs }}>
        <Text variant="display">Alerts & Notifications</Text>
        <Text variant="body" tone="secondary">
          Configure real-time Telegram alerts for automated intraday strategies and custom price levels.
        </Text>
      </View>

      {/* Strategy Notifications Card */}
      <Card style={{ gap: spacing.md, borderWidth: 1, borderColor: colors.borderSubtle }}>
        <View
          style={{
            flexDirection: isDesktop ? "row" : "column",
            justifyContent: "space-between",
            alignItems: isDesktop ? "center" : "flex-start",
            gap: spacing.sm,
          }}
        >
          <View style={{ gap: 4 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <Text variant="title">Strategy Notifications</Text>
              <Badge label="Telegram" tone="neutral" />
              <Badge
                label={`${enabledCount}/${strategies.length} Active`}
                tone={enabledCount > 0 ? "positive" : "neutral"}
              />
            </View>
            <Text variant="caption" tone="secondary">
              Direct alerts to your connected Telegram channel whenever a trade setup triggers or stop-loss is hit.
            </Text>
          </View>

          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Button
              label="Enable all"
              size="sm"
              variant="secondary"
              onPress={() => {
                strategies.forEach((s) => {
                  if (!s.enabled) strategyMutation.mutate({ key: s.key, enabled: true });
                });
              }}
            />
            <Button
              label="Mute all"
              size="sm"
              variant="ghost"
              onPress={() => {
                strategies.forEach((s) => {
                  if (s.enabled) strategyMutation.mutate({ key: s.key, enabled: false });
                });
              }}
            />
          </View>
        </View>

        {isStrategyLoading ? (
          <LoadingBlock label="Loading strategy settings…" compact />
        ) : (
          <View
            style={{
              flexDirection: isDesktop ? "row" : "column",
              flexWrap: "wrap",
              gap: spacing.sm,
            }}
          >
            {strategies.map((strat) => {
              const meta = STRATEGY_META[strat.key] ?? {
                glyph: "📈",
                color: colors.accent,
                desc: "",
              };
              return (
                <View
                  key={strat.key}
                  style={{
                    flex: isDesktop ? 1 : undefined,
                    minWidth: isDesktop ? 260 : undefined,
                    padding: spacing.md,
                    borderRadius: radius.md,
                    backgroundColor: colors.surfaceElevated,
                    borderWidth: 1,
                    borderColor: strat.enabled ? colors.border : colors.borderSubtle,
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: spacing.md,
                  }}
                >
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, flex: 1 }}>
                    <View
                      style={{
                        width: 38,
                        height: 38,
                        borderRadius: radius.md,
                        backgroundColor: colors.background,
                        alignItems: "center",
                        justifyContent: "center",
                        borderWidth: 1,
                        borderColor: meta.color + "40",
                      }}
                    >
                      <Text style={{ fontSize: 18 }}>{meta.glyph}</Text>
                    </View>
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text variant="subtitle" tone={strat.enabled ? "primary" : "secondary"}>
                        {strat.label}
                      </Text>
                      <Text variant="caption" tone="muted" numberOfLines={2}>
                        {meta.desc}
                      </Text>
                    </View>
                  </View>

                  <Switch
                    value={strat.enabled}
                    onValueChange={(val) =>
                      strategyMutation.mutate({ key: strat.key, enabled: val })
                    }
                    trackColor={{ false: colors.borderSubtle, true: colors.positive }}
                    thumbColor={strat.enabled ? "#FFFFFF" : colors.textSecondary}
                  />
                </View>
              );
            })}
          </View>
        )}

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.xs,
            paddingTop: spacing.xs,
            borderTopWidth: 1,
            borderTopColor: colors.borderSubtle,
          }}
        >
          <Text variant="caption" tone="muted">
            ℹ️ Alerts are uniquely deduplicated per stock, strategy, and trading date in Redis to prevent spam.
          </Text>
        </View>
      </Card>

      {/* Price Level Alerts */}
      <View style={{ gap: spacing.xs, marginTop: spacing.md }}>
        <Text variant="title">Price Level Alerts</Text>
        <Text variant="caption" tone="secondary">
          Custom alerts created on specific pivot and support/resistance levels.
        </Text>
      </View>

      {isAlertsLoading ? <LoadingBlock label="Loading alerts…" compact /> : null}

      <View style={{ gap: spacing.sm }}>
        {(alerts ?? []).map((a) => (
          <Card key={a.id} style={{ gap: spacing.sm }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text variant="subtitle">{a.symbol}</Text>
              <Badge label={a.isActive ? "Active" : "Muted"} tone={a.isActive ? "positive" : "neutral"} />
            </View>
            <Text variant="caption" tone="secondary">
              {a.method} · {a.levelKey.toUpperCase()} @ {formatCurrency(a.levelValueAtCreation)}
            </Text>
            <Text variant="caption" tone="secondary">
              Notify within {a.thresholdType === "percent" ? `${a.thresholdValue}%` : formatCurrency(a.thresholdValue)}
              {" · "}
              {a.channels.join(", ")}
            </Text>
            {a.currentDistancePercent !== null ? (
              <Text variant="caption" tone="muted">
                Currently {formatPercent(a.currentDistancePercent)} from level
              </Text>
            ) : null}
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Button
                label={a.isActive ? "Mute" : "Re-arm"}
                size="sm"
                variant="secondary"
                onPress={() => toggleMutation.mutate({ id: a.id, isActive: !a.isActive })}
              />
              <Button label="Delete" size="sm" variant="danger" onPress={() => deleteMutation.mutate(a.id)} />
            </View>
          </Card>
        ))}
        {!isAlertsLoading && (alerts?.length ?? 0) === 0 ? (
          <Text variant="body" tone="muted">
            No price level alerts created yet. Open a stock detail chart to configure a level alert.
          </Text>
        ) : null}
      </View>

      <StrategyAlertsModal
        visible={showConfigModal}
        onClose={() => setShowConfigModal(false)}
      />
    </Screen>
  );
}
