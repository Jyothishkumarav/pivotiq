import React, { useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Text } from "@/components/ui";
import { settingsApi } from "@/api/settings";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { StrategyAutoTradeItem } from "@/types";

export function AutoTradeSettingsCard() {
  const queryClient = useQueryClient();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [enabledDraft, setEnabledDraft] = useState<boolean>(true);
  const [allocDraft, setAllocDraft] = useState<string>("50");
  const [riskDraft, setRiskDraft] = useState<string>("1100");
  const [brokerDraft, setBrokerDraft] = useState<string>("paper");

  const { data, isLoading } = useQuery({
    queryKey: ["strategy-autotrade"],
    queryFn: () => settingsApi.getStrategyAutoTrade(),
  });

  const updateMutation = useMutation({
    mutationFn: (update: {
      key: string;
      enabled?: boolean;
      broker?: string;
      capitalAllocationPct?: number;
      maxRiskPerTrade?: number;
    }) => settingsApi.updateStrategyAutoTrade(update),
    onSuccess: (res) => {
      queryClient.setQueryData(["strategy-autotrade"], res);
      setEditingKey(null);
    },
  });

  if (isLoading) {
    return <LoadingBlock label="Loading auto-trade settings…" compact />;
  }

  const strategies = data?.strategies || [];
  const brokers = data?.availableBrokers || [
    { id: "paper", name: "Paper Trading" },
    { id: "fyers", name: "Fyers API v3" },
  ];

  const handleStartEdit = (strat: StrategyAutoTradeItem) => {
    setEditingKey(strat.key);
    setEnabledDraft(strat.enabled);
    setAllocDraft(String(strat.capitalAllocationPct));
    setRiskDraft(String(strat.maxRiskPerTrade));
    setBrokerDraft(strat.broker);
  };

  const handleSaveEdit = (key: string) => {
    updateMutation.mutate({
      key,
      enabled: enabledDraft,
      broker: brokerDraft,
      capitalAllocationPct: Number(allocDraft) || 50,
      maxRiskPerTrade: Number(riskDraft) || 1100,
    });
  };

  return (
    <Card elevated style={{ gap: spacing.md, borderLeftWidth: 3, borderLeftColor: colors.accent }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ gap: 4, flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Text variant="title" style={{ fontSize: 18 }}>Strategy Auto-Trading</Text>
            <Badge label="5x MIS Intraday" tone="neutral" />
          </View>
          <Text variant="caption" tone="secondary">
            Auto-executes Buy + SL order when a strategy setup triggers. Qty is strictly bounded by 5x leverage & max risk (₹1,100).
          </Text>
        </View>
      </View>

      {/* Rules Banner */}
      <View
        style={{
          backgroundColor: colors.surfaceElevated,
          padding: spacing.md,
          borderRadius: radius.md,
          gap: 6,
          borderWidth: 1,
          borderColor: colors.borderSubtle,
        }}
      >
        <Text variant="caption" tone="accent" style={{ fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Execution Rules Active
        </Text>
        <Text variant="caption" tone="secondary">
          • <Text variant="caption" tone="primary" style={{ fontWeight: "600" }}>5x Intraday Leverage</Text>: Strictly MIS only (Delivery/CNC blocked).
        </Text>
        <Text variant="caption" tone="secondary">
          • <Text variant="caption" tone="primary" style={{ fontWeight: "600" }}>20% Buffered SL</Text>: SL order placed immediately after buy with 20% risk buffer below tight SL.
        </Text>
        <Text variant="caption" tone="secondary">
          • <Text variant="caption" tone="primary" style={{ fontWeight: "600" }}>Max Risk Sizing</Text>: Qty calculated so potential loss never exceeds configured max SL (e.g. ₹1,100).
        </Text>
      </View>

      {/* Strategies List */}
      <View style={{ gap: spacing.sm }}>
        {strategies.map((strat) => {
          const isEditing = editingKey === strat.key;
          const isEnabled = strat.enabled;

          return (
            <Card
              key={strat.key}
              padded={false}
              style={{
                padding: spacing.md,
                backgroundColor: colors.background,
                borderWidth: 1,
                borderColor: isEnabled ? colors.accent : colors.borderSubtle,
                gap: spacing.sm,
              }}
            >
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <View style={{ gap: 2, flex: 1 }}>
                  <Text variant="subtitle" style={{ fontSize: 15 }}>{strat.label}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
                    <Badge
                      label={strat.broker === "fyers" ? "Fyers Live" : "Paper Sandbox"}
                      tone={strat.broker === "fyers" ? "positive" : "neutral"}
                    />
                    <Text variant="caption" tone="muted">
                      Alloc: {strat.capitalAllocationPct}% · Max Loss: ₹{strat.maxRiskPerTrade} · SL Buffer: {strat.slBufferPct}%
                    </Text>
                  </View>
                </View>

                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Pressable
                    onPress={() => updateMutation.mutate({ key: strat.key, enabled: !isEnabled })}
                    style={{
                      paddingHorizontal: spacing.md,
                      paddingVertical: spacing.xs,
                      borderRadius: radius.full,
                      backgroundColor: isEnabled ? colors.positive : colors.surfaceElevated,
                      borderWidth: 1,
                      borderColor: isEnabled ? colors.positive : colors.border,
                    }}
                  >
                    <Text
                      variant="caption"
                      style={{
                        color: isEnabled ? "#000" : colors.textSecondary,
                        fontWeight: "700",
                      }}
                    >
                      {isEnabled ? "ENABLED" : "DISABLED"}
                    </Text>
                  </Pressable>

                  <Button
                    label={isEditing ? "Cancel" : "Configure"}
                    variant="ghost"
                    size="sm"
                    onPress={() => (isEditing ? setEditingKey(null) : handleStartEdit(strat))}
                  />
                </View>
              </View>

              {/* Inline Edit Form */}
              {isEditing && (
                <View
                  style={{
                    marginTop: spacing.sm,
                    paddingTop: spacing.sm,
                    borderTopWidth: 1,
                    borderTopColor: colors.borderSubtle,
                    gap: spacing.md,
                  }}
                >
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
                    {/* Broker Selector */}
                    <View style={{ flex: 1, minWidth: 150, gap: 4 }}>
                      <Text variant="caption" tone="secondary">Execution Broker</Text>
                      <View style={{ flexDirection: "row", gap: 6 }}>
                        {brokers.map((b) => (
                          <Pressable
                            key={b.id}
                            onPress={() => setBrokerDraft(b.id)}
                            style={{
                              flex: 1,
                              paddingVertical: 6,
                              paddingHorizontal: 8,
                              borderRadius: radius.sm,
                              borderWidth: 1,
                              borderColor: brokerDraft === b.id ? colors.accent : colors.border,
                              backgroundColor: brokerDraft === b.id ? colors.surfaceElevated : "transparent",
                              alignItems: "center",
                            }}
                          >
                            <Text
                              variant="caption"
                              tone={brokerDraft === b.id ? "accent" : "muted"}
                              style={{ fontWeight: brokerDraft === b.id ? "700" : "400" }}
                            >
                              {b.id === "fyers" ? "Fyers Live" : "Paper Sandbox"}
                            </Text>
                          </Pressable>
                        ))}
                      </View>
                    </View>

                    {/* Capital Allocation % */}
                    <View style={{ width: 130, gap: 4 }}>
                      <Text variant="caption" tone="secondary">Capital Alloc (%)</Text>
                      <TextInput
                        value={allocDraft}
                        onChangeText={setAllocDraft}
                        keyboardType="numeric"
                        placeholder="50"
                        placeholderTextColor={colors.textMuted}
                        style={{
                          height: 36,
                          borderWidth: 1,
                          borderColor: colors.border,
                          borderRadius: radius.sm,
                          paddingHorizontal: spacing.sm,
                          color: colors.textPrimary,
                          backgroundColor: colors.background,
                          fontSize: 13,
                        }}
                      />
                    </View>

                    {/* Max Risk / SL loss */}
                    <View style={{ width: 140, gap: 4 }}>
                      <Text variant="caption" tone="secondary">Max Risk / Trade (₹)</Text>
                      <TextInput
                        value={riskDraft}
                        onChangeText={setRiskDraft}
                        keyboardType="numeric"
                        placeholder="1100"
                        placeholderTextColor={colors.textMuted}
                        style={{
                          height: 36,
                          borderWidth: 1,
                          borderColor: colors.border,
                          borderRadius: radius.sm,
                          paddingHorizontal: spacing.sm,
                          color: colors.textPrimary,
                          backgroundColor: colors.background,
                          fontSize: 13,
                        }}
                      />
                    </View>

                    {/* Status Toggle */}
                    <View style={{ width: 130, gap: 4 }}>
                      <Text variant="caption" tone="secondary">Status</Text>
                      <Pressable
                        onPress={() => setEnabledDraft(!enabledDraft)}
                        style={{
                          height: 36,
                          borderRadius: radius.sm,
                          backgroundColor: enabledDraft ? colors.positive : colors.surfaceElevated,
                          borderWidth: 1,
                          borderColor: enabledDraft ? colors.positive : colors.border,
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        <Text
                          variant="caption"
                          style={{
                            color: enabledDraft ? "#000" : colors.textSecondary,
                            fontWeight: "700",
                          }}
                        >
                          {enabledDraft ? "ENABLED" : "DISABLED"}
                        </Text>
                      </Pressable>
                    </View>
                  </View>

                  <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm }}>
                    <Button
                      label="Save Configuration"
                      size="sm"
                      loading={updateMutation.isPending}
                      onPress={() => handleSaveEdit(strat.key)}
                    />
                  </View>
                </View>
              )}
            </Card>
          );
        })}
      </View>
    </Card>
  );
}
