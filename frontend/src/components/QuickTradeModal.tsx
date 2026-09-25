import React, { useEffect, useState } from "react";
import { Modal, Platform, Pressable, TextInput, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Text } from "@/components/ui";
import { tradingApi } from "@/api/trading";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { formatCurrency } from "@/utils/format";

interface Props {
  visible: boolean;
  onClose: () => void;
  defaultSymbol?: string;
  defaultPrice?: number;
  defaultSl?: number;
  activeBroker: string;
}

export function QuickTradeModal({
  visible,
  onClose,
  defaultSymbol = "TCS",
  defaultPrice = 3000,
  defaultSl = 2950,
  activeBroker = "paper",
}: Props) {
  const queryClient = useQueryClient();
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [priceStr, setPriceStr] = useState(String(defaultPrice));
  const [slStr, setSlStr] = useState(String(defaultSl));
  const [allocStr, setAllocStr] = useState("50");
  const [maxRiskStr, setMaxRiskStr] = useState("1100");
  const [broker, setBroker] = useState(activeBroker);
  const [executionMessage, setExecutionMessage] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setSymbol(defaultSymbol);
      setPriceStr(String(defaultPrice));
      setSlStr(String(defaultSl));
      setBroker(activeBroker);
      setExecutionMessage(null);
    }
  }, [visible, defaultSymbol, defaultPrice, defaultSl, activeBroker]);

  const priceNum = Number(priceStr) || 0;
  const slNum = Number(slStr) || 0;
  const allocNum = Number(allocStr) || 50;
  const maxRiskNum = Number(maxRiskStr) || 1100;

  // Live sizing calculation
  const { data: sizing, isLoading: isSizingLoading } = useQuery({
    queryKey: ["calc-size", symbol, priceNum, slNum, broker, allocNum, maxRiskNum],
    queryFn: () =>
      tradingApi.calculateSize({
        symbol,
        stockPrice: priceNum,
        tightSl: slNum,
        broker,
        capitalAllocationPct: allocNum,
        maxRiskPerTrade: maxRiskNum,
        slBufferPct: 20.0,
      }),
    enabled: visible && priceNum > 0 && slNum > 0 && slNum < priceNum,
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      tradingApi.executeOrder({
        symbol,
        stockPrice: priceNum,
        tightSl: slNum,
        broker,
        capitalAllocationPct: allocNum,
        maxRiskPerTrade: maxRiskNum,
        slBufferPct: 20.0,
        strategy: "manual_intraday",
      }),
    onSuccess: (res) => {
      setExecutionMessage(res.message);
      queryClient.invalidateQueries({ queryKey: ["trades-orders"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["trades-funds"] });
    },
  });

  if (!visible) return null;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        onPress={onClose}
        style={{
          flex: 1,
          backgroundColor: "rgba(0,0,0,0.75)",
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.md,
        }}
      >
        <Pressable
          onPress={(e) => e.stopPropagation()}
          style={{ width: "100%", maxWidth: 540 }}
        >
          <Card
            elevated
            style={{
              gap: spacing.lg,
              borderTopWidth: 4,
              borderTopColor: colors.accent,
            }}
          >
            {/* Header */}
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <View style={{ gap: 2 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
                  <Text variant="title">Intraday Buy + Buffered SL</Text>
                  <Badge label="5x MIS" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  5x leverage sizing & 20% risk-buffered stop loss order placed automatically
                </Text>
              </View>

              <Pressable onPress={onClose} hitSlop={12}>
                <Text variant="bodyStrong" tone="muted" style={{ fontSize: 20 }}>✕</Text>
              </Pressable>
            </View>

            {/* Broker selector */}
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable
                onPress={() => setBroker("paper")}
                style={{
                  flex: 1,
                  paddingVertical: spacing.sm,
                  alignItems: "center",
                  borderRadius: radius.sm,
                  borderWidth: 1,
                  borderColor: broker === "paper" ? colors.accent : colors.border,
                  backgroundColor: broker === "paper" ? colors.surfaceElevated : "transparent",
                }}
              >
                <Text variant="caption" tone={broker === "paper" ? "accent" : "muted"} style={{ fontWeight: "700" }}>
                  Paper Trading
                </Text>
              </Pressable>

              <Pressable
                onPress={() => setBroker("fyers")}
                style={{
                  flex: 1,
                  paddingVertical: spacing.sm,
                  alignItems: "center",
                  borderRadius: radius.sm,
                  borderWidth: 1,
                  borderColor: broker === "fyers" ? colors.positive : colors.border,
                  backgroundColor: broker === "fyers" ? colors.surfaceElevated : "transparent",
                }}
              >
                <Text variant="caption" tone={broker === "fyers" ? "positive" : "muted"} style={{ fontWeight: "700" }}>
                  Fyers Securities Live
                </Text>
              </Pressable>
            </View>

            {/* Inputs Grid */}
            <View style={{ gap: spacing.md }}>
              <View style={{ flexDirection: "row", gap: spacing.md }}>
                <View style={{ flex: 1, gap: 4 }}>
                  <Text variant="caption" tone="secondary">Symbol (NSE)</Text>
                  <TextInput
                    value={symbol}
                    onChangeText={(t) => setSymbol(t.toUpperCase())}
                    placeholder="e.g. TCS"
                    placeholderTextColor={colors.textMuted}
                    style={{
                      height: 40,
                      borderWidth: 1,
                      borderColor: colors.border,
                      borderRadius: radius.sm,
                      paddingHorizontal: spacing.sm,
                      color: colors.textPrimary,
                      backgroundColor: colors.background,
                      fontWeight: "700",
                    }}
                  />
                </View>

                <View style={{ flex: 1, gap: 4 }}>
                  <Text variant="caption" tone="secondary">Stock Price (₹)</Text>
                  <TextInput
                    value={priceStr}
                    onChangeText={setPriceStr}
                    keyboardType="numeric"
                    placeholder="3000"
                    placeholderTextColor={colors.textMuted}
                    style={{
                      height: 40,
                      borderWidth: 1,
                      borderColor: colors.border,
                      borderRadius: radius.sm,
                      paddingHorizontal: spacing.sm,
                      color: colors.textPrimary,
                      backgroundColor: colors.background,
                    }}
                  />
                </View>
              </View>

              <View style={{ flexDirection: "row", gap: spacing.md }}>
                <View style={{ flex: 1, gap: 4 }}>
                  <Text variant="caption" tone="secondary">Tight Stop-Loss (₹)</Text>
                  <TextInput
                    value={slStr}
                    onChangeText={setSlStr}
                    keyboardType="numeric"
                    placeholder="2950"
                    placeholderTextColor={colors.textMuted}
                    style={{
                      height: 40,
                      borderWidth: 1,
                      borderColor: colors.border,
                      borderRadius: radius.sm,
                      paddingHorizontal: spacing.sm,
                      color: colors.textPrimary,
                      backgroundColor: colors.background,
                    }}
                  />
                </View>

                <View style={{ flex: 1, gap: 4 }}>
                  <Text variant="caption" tone="secondary">Max SL Risk Allowed (₹)</Text>
                  <TextInput
                    value={maxRiskStr}
                    onChangeText={setMaxRiskStr}
                    keyboardType="numeric"
                    placeholder="1100"
                    placeholderTextColor={colors.textMuted}
                    style={{
                      height: 40,
                      borderWidth: 1,
                      borderColor: colors.border,
                      borderRadius: radius.sm,
                      paddingHorizontal: spacing.sm,
                      color: colors.textPrimary,
                      backgroundColor: colors.background,
                    }}
                  />
                </View>
              </View>
            </View>

            {/* Calculation / Risk Summary Card */}
            {sizing ? (
              <View
                style={{
                  backgroundColor: colors.surfaceElevated,
                  padding: spacing.md,
                  borderRadius: radius.md,
                  gap: spacing.sm,
                  borderWidth: 1,
                  borderColor: colors.borderSubtle,
                }}
              >
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="caption" tone="muted">Buffered Stop-Loss (20% risk buffer)</Text>
                  <Text variant="subtitle" tone="accent" style={{ fontVariant: ["tabular-nums"] }}>
                    {formatCurrency(sizing.bufferedSl)}
                  </Text>
                </View>

                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="caption" tone="muted">Allocated Capital & 5x Buying Power</Text>
                  <Text variant="mono">{formatCurrency(sizing.tradeCapital)} → {formatCurrency(sizing.purchasingPower)}</Text>
                </View>

                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="caption" tone="muted">Optimal Quantity (SL risk bounded)</Text>
                  <Text variant="subtitle" tone="positive" style={{ fontSize: 18, fontVariant: ["tabular-nums"] }}>
                    {sizing.qty} shares
                  </Text>
                </View>

                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="caption" tone="muted">Margin Required (at 5x)</Text>
                  <Text variant="mono">{formatCurrency(sizing.marginRequired)}</Text>
                </View>

                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="caption" tone="muted">Total Worst-Case Risk (if SL hit)</Text>
                  <Text variant="mono" tone="negative">
                    {formatCurrency(sizing.totalRisk)} (Cap: {formatCurrency(sizing.maxRiskAllowed)})
                  </Text>
                </View>
              </View>
            ) : null}

            {/* Success / Error Message */}
            {executionMessage ? (
              <View
                style={{
                  backgroundColor: colors.surfaceElevated,
                  padding: spacing.md,
                  borderRadius: radius.md,
                  borderLeftWidth: 3,
                  borderLeftColor: colors.positive,
                }}
              >
                <Text variant="caption" tone="positive" style={{ fontWeight: "600" }}>
                  {executionMessage}
                </Text>
              </View>
            ) : null}

            {/* Actions */}
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm }}>
              <Button label="Close" variant="ghost" onPress={onClose} />
              <Button
                label={
                  executeMutation.isPending
                    ? "Placing Buy + SL…"
                    : `Buy ${sizing ? sizing.qty : ""} @ MKT + SL @ ₹${sizing ? sizing.bufferedSl : ""}`
                }
                loading={executeMutation.isPending}
                disabled={!sizing || sizing.qty <= 0 || executeMutation.isPending}
                onPress={() => executeMutation.mutate()}
              />
            </View>
          </Card>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
