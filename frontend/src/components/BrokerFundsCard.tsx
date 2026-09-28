import React from "react";
import { View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Text } from "@/components/ui";
import { tradingApi } from "@/api/trading";
import { colors, spacing } from "@/theme/tokens";
import { formatCurrency } from "@/utils/format";

interface Props {
  broker: string;
  onOpenQuickTrade: () => void;
  date?: string | null;
}

export function BrokerFundsCard({ broker, onOpenQuickTrade, date }: Props) {
  const queryClient = useQueryClient();
  const { data: funds, isLoading } = useQuery({
    queryKey: ["trades-funds", broker, date],
    queryFn: () => tradingApi.getFunds(broker, date),
    refetchInterval: 15000,
  });

  const resetMutation = useMutation({
    mutationFn: tradingApi.resetPaperAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades-funds"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
    },
  });

  const avail = funds?.available_balance || 0;
  const buyingPower = funds?.buying_power_5x || avail * 5;
  const utilized = funds?.utilized_margin || 0;
  const total = funds?.total_balance || avail + utilized;

  return (
    <Card
      elevated
      style={{
        gap: spacing.md,
        borderTopWidth: 3,
        borderTopColor: broker === "fyers" ? colors.positive : colors.accent,
      }}
    >
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <Text variant="caption" tone="secondary" style={{ textTransform: "uppercase", letterSpacing: 1.5 }}>
            Account Balance & Margin
          </Text>
          <Badge
            label={broker === "fyers" ? "Fyers API v3 Live" : "Paper Sandbox"}
            tone={broker === "fyers" ? "positive" : "neutral"}
          />
          <Badge label="5x MIS Leverage" tone="neutral" />
        </View>

        <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
          {broker !== "fyers" && (
            <Button
              label="Reset Paper (1L)"
              size="sm"
              variant="secondary"
              loading={resetMutation.isPending}
              onPress={() => {
                if (typeof window !== "undefined" && window.confirm) {
                  if (window.confirm("Reset paper trading portfolio back to fresh ₹1,00,000 capital?")) {
                    resetMutation.mutate();
                  }
                } else {
                  resetMutation.mutate();
                }
              }}
            />
          )}
          <Button label="+ Quick Trade (Buy + SL)" size="sm" onPress={onOpenQuickTrade} />
        </View>
      </View>

      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "flex-end",
          flexWrap: "wrap",
          gap: spacing.md,
        }}
      >
        {/* 5x Buying Power Hero */}
        <View style={{ gap: 2, flex: 1, minWidth: 200 }}>
          <Text variant="caption" tone="muted">
            Intraday 5x Buying Power
          </Text>
          <Text variant="title" style={{ fontSize: 24, letterSpacing: -0.5, color: colors.positive }}>
            {formatCurrency(buyingPower)}
          </Text>
          <Text variant="caption" tone="secondary">
            Based on {formatCurrency(avail)} available margin with 5x leverage
          </Text>
        </View>

        {/* Metrics Grid */}
        <View style={{ flexDirection: "row", gap: spacing.xl, flexWrap: "wrap" }}>
          <View style={{ gap: 2 }}>
            <Text variant="caption" tone="muted">Available Balance</Text>
            <Text variant="mono">{formatCurrency(avail)}</Text>
          </View>

          <View style={{ gap: 2 }}>
            <Text variant="caption" tone="muted">Utilized Margin</Text>
            <Text variant="mono">{formatCurrency(utilized)}</Text>
          </View>

          <View style={{ gap: 2 }}>
            <Text variant="caption" tone="muted">Total Account Value</Text>
            <Text variant="mono">{formatCurrency(total)}</Text>
          </View>
        </View>
      </View>
    </Card>
  );
}
