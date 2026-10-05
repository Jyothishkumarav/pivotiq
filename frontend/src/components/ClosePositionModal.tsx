import React, { useEffect, useMemo, useState } from "react";
import { Modal, Platform, Pressable, TextInput, View } from "react-native";
import { Badge, Button, Card, Text } from "@/components/ui";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { formatCurrency, formatPercent } from "@/utils/format";
import { Position } from "@/types";

interface Props {
  visible: boolean;
  position: Position | null;
  linkedSl?: number | null;
  onClose: () => void;
  onConfirm: (exitPrice: number) => void;
  isClosing: boolean;
}

export function ClosePositionModal({
  visible,
  position,
  linkedSl,
  onClose,
  onConfirm,
  isClosing,
}: Props) {
  const [exitPriceStr, setExitPriceStr] = useState<string>("");

  const isBuy = (position?.netQty ?? 0) > 0;
  const entryPrice = position?.avgPrice || 0;
  const ltp = position?.ltp || entryPrice;
  const absQty = Math.abs(position?.netQty || 0);
  const effectiveSl = linkedSl || position?.stopLoss || null;

  // Initialize or reset exitPriceStr to current LTP when modal becomes visible or position changes
  useEffect(() => {
    if (visible && position) {
      const defaultPrice = position.ltp > 0 ? position.ltp : position.avgPrice;
      setExitPriceStr(defaultPrice ? defaultPrice.toFixed(2) : "");
    }
  }, [visible, position]);

  // Calculate SL risk distance and target milestones (1.0R, 1.5R, 2.0R)
  const targets = useMemo(() => {
    if (!position || !effectiveSl || effectiveSl <= 0 || entryPrice <= 0) {
      return null;
    }

    const slDiff = isBuy ? entryPrice - effectiveSl : effectiveSl - entryPrice;
    if (slDiff <= 0) return null;

    const roundTick = (v: number) => Math.round(v * 20) / 20;

    const t1_0 = isBuy ? roundTick(entryPrice + slDiff) : roundTick(entryPrice - slDiff);
    const t1_5 = isBuy ? roundTick(entryPrice + 1.5 * slDiff) : roundTick(entryPrice - 1.5 * slDiff);
    const t2_0 = isBuy ? roundTick(entryPrice + 2.0 * slDiff) : roundTick(entryPrice - 2.0 * slDiff);

    return {
      slDiff: roundTick(slDiff),
      t1_0,
      t1_5,
      t2_0,
    };
  }, [position, effectiveSl, entryPrice, isBuy]);

  if (!visible || !position) return null;

  const exitPriceNum = Number(exitPriceStr) || 0;

  // Projected P&L calculation at the chosen exit price
  const projectedPnl = isBuy
    ? (exitPriceNum - entryPrice) * absQty
    : (entryPrice - exitPriceNum) * absQty;
  const projectedPct = entryPrice > 0 ? ((exitPriceNum - entryPrice) / entryPrice) * 100 * (isBuy ? 1 : -1) : 0;
  const isProfit = projectedPnl >= 0;

  const handleSubmit = () => {
    if (exitPriceNum <= 0) return;
    onConfirm(exitPriceNum);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        onPress={onClose}
        style={{
          flex: 1,
          backgroundColor: "rgba(0,0,0,0.78)",
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.md,
        }}
      >
        <Pressable
          onPress={(e) => e.stopPropagation()}
          style={{
            width: "100%",
            maxWidth: 480,
            borderRadius: radius.lg,
            borderWidth: 1.5,
            borderColor: colors.border,
            backgroundColor: colors.surface,
            padding: spacing.lg,
            gap: spacing.md,
            ...(Platform.OS === "web" ? { boxShadow: "0 16px 40px rgba(0,0,0,0.6)" } : {}),
          }}
        >
          {/* Header */}
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <Badge label={isBuy ? "BUY / LONG" : "SELL / SHORT"} tone={isBuy ? "positive" : "negative"} />
              <Text variant="title" style={{ fontSize: 20, fontWeight: "800", color: colors.textPrimary }}>
                {position.symbol}
              </Text>
              <Text variant="caption" tone="muted">
                ({absQty} {absQty === 1 ? "share" : "shares"})
              </Text>
            </View>

            <Pressable
              onPress={onClose}
              hitSlop={8}
              style={{
                width: 28,
                height: 28,
                borderRadius: radius.full,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: colors.surfaceElevated,
              }}
            >
              <Text variant="bodyStrong" style={{ color: colors.textMuted }}>×</Text>
            </Pressable>
          </View>

          {/* Price & SL Context Banner */}
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              backgroundColor: colors.surfaceElevated,
              borderRadius: radius.md,
              padding: spacing.md,
              borderWidth: 1,
              borderColor: colors.borderSubtle,
            }}
          >
            <View style={{ gap: 2 }}>
              <Text variant="caption" tone="muted">Entry Avg</Text>
              <Text variant="subtitle" style={{ fontWeight: "700", color: colors.textPrimary }}>
                {formatCurrency(entryPrice)}
              </Text>
            </View>

            <View style={{ gap: 2, alignItems: "center" }}>
              <Text variant="caption" tone="muted">Current LTP</Text>
              <Text variant="subtitle" tone="accent" style={{ fontWeight: "700" }}>
                {formatCurrency(ltp)}
              </Text>
            </View>

            <View style={{ gap: 2, alignItems: "flex-end" }}>
              <Text variant="caption" tone="muted">
                {effectiveSl ? "Stop-Loss" : "SL Status"}
              </Text>
              <Text
                variant="subtitle"
                style={{
                  fontWeight: "700",
                  color: effectiveSl ? colors.warning : colors.textMuted,
                }}
              >
                {effectiveSl ? formatCurrency(effectiveSl) : "None"}
              </Text>
            </View>
          </View>

          {/* Quick Target Milestone Selector Buttons (Stretched SL) */}
          <View style={{ gap: spacing.xs }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text variant="caption" tone="secondary" style={{ fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 }}>
                Quick Set Exit Price:
              </Text>
              {targets && (
                <Text variant="caption" tone="muted">
                  SL Diff (1R): ₹{targets.slDiff.toFixed(2)}
                </Text>
              )}
            </View>

            <View style={{ flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" }}>
              {/* Button: Current LTP */}
              <Pressable
                onPress={() => setExitPriceStr(ltp.toFixed(2))}
                style={({ hovered }: any) => ({
                  flex: 1,
                  minWidth: 90,
                  paddingVertical: 7,
                  paddingHorizontal: 8,
                  borderRadius: radius.sm,
                  alignItems: "center",
                  justifyContent: "center",
                  borderWidth: 1,
                  borderColor: Math.abs(exitPriceNum - ltp) < 0.02 ? colors.accent : colors.borderSubtle,
                  backgroundColor: Math.abs(exitPriceNum - ltp) < 0.02 ? "rgba(99,102,241,0.15)" : hovered ? colors.surfaceElevated : "transparent",
                })}
              >
                <Text variant="caption" style={{ fontWeight: "700", color: colors.accent, fontSize: 11 }}>
                  LTP (Market)
                </Text>
                <Text variant="caption" style={{ fontWeight: "600", color: colors.textPrimary, fontSize: 12 }}>
                  ₹{ltp.toFixed(2)}
                </Text>
              </Pressable>

              {/* Button: 1.0R */}
              {targets && (
                <Pressable
                  onPress={() => setExitPriceStr(targets.t1_0.toFixed(2))}
                  style={({ hovered }: any) => ({
                    flex: 1,
                    minWidth: 85,
                    paddingVertical: 7,
                    paddingHorizontal: 8,
                    borderRadius: radius.sm,
                    alignItems: "center",
                    justifyContent: "center",
                    borderWidth: 1,
                    borderColor: Math.abs(exitPriceNum - targets.t1_0) < 0.02 ? colors.positive : colors.borderSubtle,
                    backgroundColor: Math.abs(exitPriceNum - targets.t1_0) < 0.02 ? "rgba(34,197,94,0.15)" : hovered ? colors.surfaceElevated : "transparent",
                  })}
                >
                  <Text variant="caption" style={{ fontWeight: "700", color: colors.positive, fontSize: 11 }}>
                    1.0R Target
                  </Text>
                  <Text variant="caption" style={{ fontWeight: "600", color: colors.textPrimary, fontSize: 12 }}>
                    ₹{targets.t1_0.toFixed(2)}
                  </Text>
                </Pressable>
              )}

              {/* Button: 1.5R */}
              {targets && (
                <Pressable
                  onPress={() => setExitPriceStr(targets.t1_5.toFixed(2))}
                  style={({ hovered }: any) => ({
                    flex: 1,
                    minWidth: 85,
                    paddingVertical: 7,
                    paddingHorizontal: 8,
                    borderRadius: radius.sm,
                    alignItems: "center",
                    justifyContent: "center",
                    borderWidth: 1,
                    borderColor: Math.abs(exitPriceNum - targets.t1_5) < 0.02 ? colors.positive : colors.borderSubtle,
                    backgroundColor: Math.abs(exitPriceNum - targets.t1_5) < 0.02 ? "rgba(34,197,94,0.15)" : hovered ? colors.surfaceElevated : "transparent",
                  })}
                >
                  <Text variant="caption" style={{ fontWeight: "700", color: colors.positive, fontSize: 11 }}>
                    1.5R Target
                  </Text>
                  <Text variant="caption" style={{ fontWeight: "600", color: colors.textPrimary, fontSize: 12 }}>
                    ₹{targets.t1_5.toFixed(2)}
                  </Text>
                </Pressable>
              )}

              {/* Button: 2.0R (Default 2x SL) */}
              {targets && (
                <Pressable
                  onPress={() => setExitPriceStr(targets.t2_0.toFixed(2))}
                  style={({ hovered }: any) => ({
                    flex: 1,
                    minWidth: 100,
                    paddingVertical: 7,
                    paddingHorizontal: 8,
                    borderRadius: radius.sm,
                    alignItems: "center",
                    justifyContent: "center",
                    borderWidth: 1.5,
                    borderColor: Math.abs(exitPriceNum - targets.t2_0) < 0.02 ? colors.positive : "rgba(34,197,94,0.4)",
                    backgroundColor: Math.abs(exitPriceNum - targets.t2_0) < 0.02 ? "rgba(34,197,94,0.22)" : hovered ? colors.surfaceElevated : "rgba(34,197,94,0.08)",
                  })}
                >
                  <Text variant="caption" style={{ fontWeight: "800", color: colors.positive, fontSize: 11 }}>
                    2.0R (Default 2x)
                  </Text>
                  <Text variant="caption" style={{ fontWeight: "700", color: colors.textPrimary, fontSize: 12 }}>
                    ₹{targets.t2_0.toFixed(2)}
                  </Text>
                </Pressable>
              )}
            </View>
          </View>

          {/* Editable Exit Price Input */}
          <View style={{ gap: spacing.xs }}>
            <Text variant="caption" tone="muted" style={{ fontWeight: "700" }}>
              Exit Price (₹):
            </Text>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                backgroundColor: colors.background,
                borderRadius: radius.md,
                borderWidth: 1.5,
                borderColor: exitPriceNum > 0 ? colors.accent : colors.border,
                paddingHorizontal: spacing.md,
                height: 48,
              }}
            >
              <Text variant="bodyStrong" tone="muted" style={{ marginRight: spacing.xs, fontSize: 16 }}>
                ₹
              </Text>
              <TextInput
                value={exitPriceStr}
                onChangeText={setExitPriceStr}
                keyboardType="numeric"
                placeholder={ltp ? ltp.toFixed(2) : "0.00"}
                placeholderTextColor={colors.textMuted}
                style={{
                  flex: 1,
                  color: colors.textPrimary,
                  fontSize: 18,
                  fontWeight: "700",
                  fontVariant: ["tabular-nums"],
                  ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
                }}
              />
              <Pressable
                onPress={() => setExitPriceStr(ltp.toFixed(2))}
                style={{
                  paddingVertical: 4,
                  paddingHorizontal: 8,
                  backgroundColor: colors.surfaceElevated,
                  borderRadius: radius.sm,
                  borderWidth: 1,
                  borderColor: colors.borderSubtle,
                }}
              >
                <Text variant="caption" tone="accent" style={{ fontWeight: "700", fontSize: 11 }}>
                  Reset to LTP
                </Text>
              </Pressable>
            </View>
          </View>

          {/* P&L Preview at this Exit Price */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              backgroundColor: isProfit ? "rgba(34,197,94,0.10)" : "rgba(239,68,68,0.10)",
              borderRadius: radius.md,
              padding: spacing.md,
              borderWidth: 1,
              borderColor: isProfit ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)",
            }}
          >
            <View style={{ gap: 2 }}>
              <Text variant="caption" tone="muted">Projected Exit P&L</Text>
              <Text
                variant="subtitle"
                style={{
                  fontWeight: "800",
                  fontSize: 16,
                  color: isProfit ? colors.positive : colors.negative,
                }}
              >
                {isProfit ? "+" : ""}{formatCurrency(projectedPnl)} ({isProfit ? "+" : ""}{projectedPct.toFixed(2)}%)
              </Text>
            </View>

            <Badge
              label={isProfit ? "PROFITABLE CLOSE" : "LOSS CLOSE"}
              tone={isProfit ? "positive" : "negative"}
            />
          </View>

          {/* Disclaimer note */}
          <Text variant="caption" tone="muted" style={{ fontSize: 11 }}>
            ℹ️ Position will be closed at ₹{exitPriceNum.toFixed(2)}, linked stop-loss orders cancelled, and trade status updated. An alert will be sent to the Trade Channel.
          </Text>

          {/* Modal Actions */}
          <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.xs }}>
            <Button
              label="Cancel"
              variant="secondary"
              onPress={onClose}
              style={{ flex: 1 }}
              disabled={isClosing}
            />
            <Button
              label={isClosing ? "Closing…" : `Close at ₹${exitPriceNum > 0 ? exitPriceNum.toFixed(2) : "LTP"}`}
              onPress={handleSubmit}
              loading={isClosing}
              disabled={exitPriceNum <= 0 || isClosing}
              variant={isProfit ? "primary" : "danger"}
              style={{ flex: 2 }}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
