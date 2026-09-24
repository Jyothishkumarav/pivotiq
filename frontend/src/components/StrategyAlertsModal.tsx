import React, { useEffect, useState } from "react";
import {
  Modal,
  Platform,
  Pressable,
  Switch,
  TextInput,
  View,
} from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, LoadingBlock, Text } from "@/components/ui";
import { settingsApi, StrategyNotificationItem, TelegramChannelOption } from "@/api/settings";
import { colors, radius, spacing } from "@/theme/tokens";

interface Props {
  visible: boolean;
  onClose: () => void;
}

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  orb_vwap: "Enters on initial ORB breakout aligned with VWAP.",
  context_gated:
    "Filters breakouts using market gap bias, trend, and HL-BOS structure.",
  orb_pullback:
    "Waits for pullback to complete, enters on break of pullback high/low.",
  orb_pullback_support:
    "Early entry on break of the first supporting reversal candle.",
  orb_flow:
    "Morning window breakout with 3m close confirmation and index confluence position sizing.",
};

const STRATEGY_BADGES: Record<string, { glyph: string; color: string }> = {
  orb_vwap: { glyph: "⚡", color: "#5B8BFF" },
  context_gated: { glyph: "🛡️", color: "#9AA9C7" },
  orb_pullback: { glyph: "🔄", color: "#F5B54A" },
  orb_pullback_support: { glyph: "🎯", color: "#3DDB9F" },
  orb_flow: { glyph: "⚡", color: "#7B61FF" },
};

const DEFAULT_AVAILABLE_CHANNELS: TelegramChannelOption[] = [
  { id: "-1004449069761", name: "Pivotiq_Tuned" },
  { id: "-1004294022390", name: "PivotIQ_15_Mins_Break" },
  { id: "-1004440440854", name: "Pivotiqupdate" },
];

// ─── Per-strategy channel selector ───────────────────────────────────────────
function ChannelRow({
  stratKey,
  currentChannelId,
  currentChannelName,
  availableChannels = [],
}: {
  stratKey: string;
  currentChannelId?: string | null;
  currentChannelName?: string | null;
  availableChannels?: TelegramChannelOption[];
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [customDraft, setCustomDraft] = useState(currentChannelId ?? "");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setCustomDraft(currentChannelId ?? "");
  }, [currentChannelId]);

  const channelMutation = useMutation({
    mutationFn: ({
      key,
      id,
      name,
    }: {
      key: string;
      id: string | null;
      name?: string | null;
    }) => settingsApi.updateStrategyChannel(key, id, name),
    onSuccess: (data) => {
      queryClient.setQueryData(["strategy-channels"], data);
      queryClient.setQueryData(["strategy-notifications"], data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const channelsList =
    availableChannels.length > 0 ? availableChannels : DEFAULT_AVAILABLE_CHANNELS;

  const matched = channelsList.find(
    (c) =>
      c.id === currentChannelId ||
      (currentChannelName && c.name.toLowerCase() === currentChannelName.toLowerCase())
  );

  const displayName =
    currentChannelName || matched?.name || (currentChannelId ? currentChannelId : "Default Channel");

  const handleSelectChannel = (channel: TelegramChannelOption) => {
    setCustomMode(false);
    channelMutation.mutate({ key: stratKey, id: channel.id, name: channel.name });
  };

  const handleCustomSave = () => {
    const trimmed = customDraft.trim();
    if (!trimmed) {
      setCustomMode(false);
      channelMutation.mutate({ key: stratKey, id: null });
      return;
    }
    channelMutation.mutate({ key: stratKey, id: trimmed });
  };

  return (
    <View
      style={{
        marginTop: spacing.xs,
        borderTopWidth: 1,
        borderTopColor: colors.borderSubtle,
        paddingTop: spacing.xs,
        gap: spacing.xs,
      }}
    >
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        style={({ hovered }: any) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.xs,
          paddingVertical: 4,
          paddingHorizontal: 6,
          borderRadius: radius.sm,
          backgroundColor: hovered ? `${colors.accent}15` : "transparent",
          alignSelf: "flex-start",
        })}
      >
        <Text style={{ fontSize: 11, color: colors.textSecondary }}>
          {expanded ? "▾" : "▸"}
        </Text>
        <Text variant="caption" tone="secondary">
          Telegram Channel:
        </Text>
        <View
          style={{
            paddingHorizontal: 8,
            paddingVertical: 3,
            borderRadius: 99,
            backgroundColor: `${colors.accent}20`,
            borderWidth: 1,
            borderColor: `${colors.accent}45`,
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
          }}
        >
          <Text style={{ fontSize: 11 }}>📢</Text>
          <Text
            style={{
              fontSize: 12,
              color: colors.accent,
              fontWeight: "600",
            }}
          >
            {displayName}
          </Text>
        </View>
        <Text style={{ fontSize: 10, color: colors.textSecondary }}>
          {expanded ? "▲ Change" : "▼ Change"}
        </Text>
      </Pressable>

      {expanded && (
        <View
          style={{
            marginTop: 4,
            padding: spacing.sm,
            borderRadius: radius.md,
            backgroundColor: colors.surfaceElevated,
            borderWidth: 1,
            borderColor: colors.borderSubtle,
            gap: spacing.sm,
          }}
        >
          <Text variant="caption" tone="secondary">
            Select destination Telegram channel for alerts:
          </Text>

          {/* Channel selector pills */}
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {channelsList.map((c) => {
              const isSelected =
                currentChannelId === c.id ||
                (!currentChannelId && matched?.id === c.id) ||
                (currentChannelName && c.name.toLowerCase() === currentChannelName.toLowerCase());

              return (
                <Pressable
                  key={c.id}
                  onPress={() => handleSelectChannel(c)}
                  disabled={channelMutation.isPending}
                  style={({ hovered }: any) => ({
                    paddingHorizontal: spacing.sm,
                    paddingVertical: 6,
                    borderRadius: radius.sm,
                    borderWidth: 1,
                    borderColor: isSelected
                      ? colors.accent
                      : hovered
                      ? colors.border
                      : colors.borderSubtle,
                    backgroundColor: isSelected
                      ? `${colors.accent}25`
                      : hovered
                      ? colors.surface
                      : colors.background,
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                  })}
                >
                  <Text style={{ fontSize: 11 }}>📢</Text>
                  <Text
                    style={{
                      fontSize: 12,
                      fontWeight: isSelected ? "600" : "400",
                      color: isSelected ? colors.accent : colors.text,
                    }}
                  >
                    {c.name}
                  </Text>
                  {isSelected && (
                    <Text style={{ fontSize: 11, color: colors.accent, fontWeight: "700" }}>
                      ✓
                    </Text>
                  )}
                </Pressable>
              );
            })}

            {/* Custom ID toggle */}
            <Pressable
              onPress={() => setCustomMode((v) => !v)}
              style={({ hovered }: any) => ({
                paddingHorizontal: spacing.sm,
                paddingVertical: 6,
                borderRadius: radius.sm,
                borderWidth: 1,
                borderColor: customMode ? colors.accent : hovered ? colors.border : colors.borderSubtle,
                backgroundColor: customMode
                  ? `${colors.accent}15`
                  : hovered
                  ? colors.surface
                  : colors.background,
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              })}
            >
              <Text style={{ fontSize: 11 }}>✏️</Text>
              <Text
                style={{
                  fontSize: 12,
                  fontWeight: customMode ? "600" : "400",
                  color: customMode ? colors.accent : colors.textSecondary,
                }}
              >
                Custom ID…
              </Text>
            </Pressable>
          </View>

          {/* Custom ID input */}
          {customMode && (
            <View style={{ marginTop: spacing.xs, gap: spacing.xs }}>
              <Text variant="caption" tone="secondary">
                Enter Telegram Chat/Channel ID (e.g. -1001234567890):
              </Text>
              <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
                <TextInput
                  value={customDraft}
                  onChangeText={(t) => {
                    setCustomDraft(t);
                    setSaved(false);
                  }}
                  placeholder="-100xxxxxxxxxx"
                  placeholderTextColor={colors.textSecondary}
                  style={{
                    flex: 1,
                    height: 36,
                    borderRadius: radius.sm,
                    borderWidth: 1,
                    borderColor: colors.border,
                    backgroundColor: colors.background,
                    color: colors.text,
                    paddingHorizontal: spacing.sm,
                    fontSize: 13,
                    ...(Platform.OS === "web" ? { fontFamily: "monospace" } : {}),
                  }}
                />
                <Pressable
                  onPress={handleCustomSave}
                  disabled={channelMutation.isPending}
                  style={({ hovered }: any) => ({
                    paddingHorizontal: spacing.md,
                    height: 36,
                    borderRadius: radius.sm,
                    backgroundColor: saved
                      ? colors.positive
                      : hovered
                      ? `${colors.accent}cc`
                      : colors.accent,
                    justifyContent: "center",
                    alignItems: "center",
                    opacity: channelMutation.isPending ? 0.6 : 1,
                  })}
                >
                  <Text style={{ fontSize: 12, color: "#fff", fontWeight: "600" }}>
                    {saved ? "✓ Saved" : channelMutation.isPending ? "Saving…" : "Save"}
                  </Text>
                </Pressable>
              </View>
            </View>
          )}

          {saved && (
            <Text variant="caption" style={{ color: colors.positive }}>
              ✓ Channel updated successfully
            </Text>
          )}

          {channelMutation.isError && (
            <Text variant="caption" style={{ color: colors.negative }}>
              Failed to save channel. Please try again.
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

// ─── Main modal ───────────────────────────────────────────────────────────────
export function StrategyAlertsModal({ visible, onClose }: Props) {
  const queryClient = useQueryClient();

  const { data: notifData, isLoading: notifLoading } = useQuery({
    queryKey: ["strategy-notifications"],
    queryFn: settingsApi.getStrategyNotifications,
    enabled: visible,
  });

  const { data: channelData } = useQuery({
    queryKey: ["strategy-channels"],
    queryFn: settingsApi.getStrategyChannels,
    enabled: visible,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
      settingsApi.updateStrategyNotification(key, enabled),
    onMutate: async ({ key, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ["strategy-notifications"] });
      const prev = queryClient.getQueryData<{ strategies: StrategyNotificationItem[] }>(
        ["strategy-notifications"]
      );
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

  const HIDDEN_STRATEGIES = ["orb_vwap", "context_gated"];
  const strategies = (notifData?.strategies ?? []).filter(
    (s) => !HIDDEN_STRATEGIES.includes(s.key)
  );
  const enabledCount = strategies.filter((s) => s.enabled).length;

  const channelSource =
    channelData?.strategies && channelData.strategies.length > 0
      ? channelData.strategies
      : notifData?.strategies ?? [];

  const channelMap: Record<string, { id: string | null | undefined; name: string | null | undefined }> =
    Object.fromEntries(
      channelSource.map((s) => [
        s.key,
        { id: s.telegramChannelId, name: s.telegramChannelName },
      ])
    );

  const availableChannels: TelegramChannelOption[] =
    channelData?.availableChannels && channelData.availableChannels.length > 0
      ? channelData.availableChannels
      : notifData?.availableChannels && notifData.availableChannels.length > 0
      ? notifData.availableChannels
      : DEFAULT_AVAILABLE_CHANNELS;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
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
            maxWidth: 560,
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
                Toggle strategies on/off and assign a dedicated Telegram Channel ID per
                strategy to keep alerts organised.
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

          {/* Strategy list */}
          {notifLoading && strategies.length === 0 ? (
            <LoadingBlock label="Loading strategy settings…" compact />
          ) : (
            <View style={{ gap: spacing.sm }}>
              {strategies.map((strat) => {
                const badge = STRATEGY_BADGES[strat.key] ?? { glyph: "📈", color: colors.accent };
                const desc = STRATEGY_DESCRIPTIONS[strat.key] ?? "";
                const channelInfo = channelMap[strat.key];
                return (
                  <View
                    key={strat.key}
                    style={{
                      padding: spacing.md,
                      borderRadius: radius.md,
                      borderWidth: 1,
                      borderColor: strat.enabled ? colors.border : colors.borderSubtle,
                      backgroundColor: strat.enabled ? `${colors.surfaceElevated}` : "transparent",
                    }}
                  >
                    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
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
                            <Text variant="caption" tone="muted" numberOfLines={2}>{desc}</Text>
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
                    <ChannelRow
                      stratKey={strat.key}
                      currentChannelId={channelInfo?.id}
                      currentChannelName={channelInfo?.name}
                      availableChannels={availableChannels}
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
