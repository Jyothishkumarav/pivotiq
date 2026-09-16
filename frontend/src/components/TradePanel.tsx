import React, { useMemo, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Segmented, Text } from "@/components/ui";
import { tradingApi } from "@/api/trading";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { formatCurrency } from "@/utils/format";
import { OrderStatus, OrderType, Segment, Side } from "@/types";

interface Props {
  symbol: string;
  ltp: number;
  dayChangePercent: number;
}

interface LastFill {
  side: Side;
  qty: number;
  price: number;
  status: OrderStatus;
}

const SIDE_OPTIONS = [
  { value: "buy" as Side, label: "Buy", tone: "positive" as const },
  { value: "sell" as Side, label: "Sell", tone: "negative" as const },
];

const SEGMENT_OPTIONS = [
  { value: "intraday" as Segment, label: "Intraday (MIS)" },
  { value: "delivery" as Segment, label: "Delivery (CNC)" },
];

const ORDER_TYPE_OPTIONS = [
  { value: "market" as OrderType, label: "Market" },
  { value: "limit" as OrderType, label: "Limit" },
];

function Stepper({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        width: 36,
        height: 36,
        borderRadius: radius.sm,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.background,
      }}
    >
      <Text variant="bodyStrong">{label}</Text>
    </Pressable>
  );
}

function SummaryRow({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" }}>
      <Text variant={strong ? "bodyStrong" : "caption"} tone={strong ? "primary" : "secondary"}>
        {label}
      </Text>
      <Text variant={strong ? "subtitle" : "mono"} tone={strong ? "primary" : "primary"}>
        {value}
      </Text>
    </View>
  );
}

export function TradePanel({ symbol, ltp, dayChangePercent }: Props) {
  const queryClient = useQueryClient();
  const [side, setSide] = useState<Side>("buy");
  const [segment, setSegment] = useState<Segment>("delivery");
  const [orderType, setOrderType] = useState<OrderType>("market");
  const [qty, setQty] = useState("1");
  const [limitPrice, setLimitPrice] = useState<string>(ltp.toFixed(2));
  const [lastFill, setLastFill] = useState<LastFill | null>(null);

  const qtyNum = Math.max(0, Math.floor(Number(qty) || 0));
  const limitNum = Number(limitPrice) || 0;
  const pricePreview = orderType === "market" ? ltp : limitNum;
  const orderValue = pricePreview * qtyNum;
  const isDayUp = dayChangePercent >= 0;

  const placeTrade = useMutation({
    mutationFn: () =>
      tradingApi.placeTrade({
        symbol,
        segment,
        side,
        qty: qtyNum,
        orderType,
        limitPrice: orderType === "limit" ? limitNum : undefined,
      }),
    onSuccess: (trade) => {
      setLastFill({ side: trade.side, qty: trade.qty, price: trade.price, status: trade.status });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });

  const submitLabel = useMemo(() => {
    if (qtyNum === 0) return "Enter quantity";
    if (orderType === "limit" && limitNum <= 0) return "Enter limit price";
    const verb = side === "buy" ? "Buy" : "Sell";
    return `${verb} ${qtyNum} @ ${orderType === "market" ? "market" : formatCurrency(limitNum)}`;
  }, [side, orderType, qtyNum, limitNum]);

  const canSubmit = qtyNum > 0 && (orderType === "market" || limitNum > 0);

  return (
    <Card
      elevated
      style={{
        gap: spacing.lg,
        borderTopWidth: 3,
        borderTopColor: side === "buy" ? colors.positive : colors.negative,
      }}
    >
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View>
          <Text variant="subtitle">Place order</Text>
          <Text variant="caption" tone="secondary">
            {symbol} · LTP {formatCurrency(ltp)}{" "}
            <Text variant="caption" tone={isDayUp ? "positive" : "negative"}>
              ({isDayUp ? "+" : ""}
              {dayChangePercent.toFixed(2)}%)
            </Text>
          </Text>
        </View>
        <Badge label="Simulated" tone="warning" />
      </View>

      <View style={{ gap: spacing.sm }}>
        <Text variant="caption" tone="secondary">
          Transaction
        </Text>
        <Segmented value={side} options={SIDE_OPTIONS} onChange={setSide} />
      </View>

      <View style={{ gap: spacing.sm }}>
        <Text variant="caption" tone="secondary">
          Product
        </Text>
        <Segmented value={segment} options={SEGMENT_OPTIONS} onChange={setSegment} />
      </View>

      <View style={{ gap: spacing.sm }}>
        <Text variant="caption" tone="secondary">
          Order type
        </Text>
        <Segmented value={orderType} options={ORDER_TYPE_OPTIONS} onChange={setOrderType} />
      </View>

      <View style={{ flexDirection: "row", gap: spacing.md }}>
        <View style={{ flex: 1, gap: spacing.sm }}>
          <Text variant="caption" tone="secondary">
            Quantity
          </Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Stepper label="−" onPress={() => setQty(String(Math.max(1, qtyNum - 1)))} />
            <TextInput
              value={qty}
              onChangeText={(v) => setQty(v.replace(/[^0-9]/g, ""))}
              keyboardType="number-pad"
              style={{
                flex: 1,
                height: 40,
                paddingHorizontal: spacing.md,
                borderRadius: radius.sm,
                borderWidth: 1,
                borderColor: colors.border,
                backgroundColor: colors.background,
                color: colors.textPrimary,
                textAlign: "center",
                ...typography.bodyStrong,
              }}
            />
            <Stepper label="+" onPress={() => setQty(String(qtyNum + 1))} />
          </View>
        </View>

        {orderType === "limit" ? (
          <View style={{ flex: 1, gap: spacing.sm }}>
            <Text variant="caption" tone="secondary">
              Limit price (₹)
            </Text>
            <TextInput
              value={limitPrice}
              onChangeText={(v) => setLimitPrice(v.replace(/[^0-9.]/g, ""))}
              keyboardType="decimal-pad"
              style={{
                height: 40,
                paddingHorizontal: spacing.md,
                borderRadius: radius.sm,
                borderWidth: 1,
                borderColor: colors.border,
                backgroundColor: colors.background,
                color: colors.textPrimary,
                ...typography.bodyStrong,
              }}
            />
          </View>
        ) : null}
      </View>

      <View
        style={{
          backgroundColor: colors.background,
          borderRadius: radius.md,
          borderWidth: 1,
          borderColor: colors.borderSubtle,
          padding: spacing.md,
          gap: spacing.sm,
        }}
      >
        <SummaryRow label={orderType === "market" ? "Estimated price" : "Limit price"} value={formatCurrency(pricePreview)} />
        <SummaryRow label="Quantity" value={String(qtyNum)} />
        <View style={{ height: 1, backgroundColor: colors.divider }} />
        <SummaryRow label="Order value" value={formatCurrency(orderValue)} strong />
      </View>

      <Button
        label={submitLabel}
        variant={side}
        onPress={() => placeTrade.mutate()}
        loading={placeTrade.isPending}
        disabled={!canSubmit}
        fullWidth
      />

      {placeTrade.isError ? (
        <Text variant="caption" tone="negative">
          {(placeTrade.error as Error).message}
        </Text>
      ) : null}

      {lastFill ? (
        <View
          style={{
            backgroundColor: colors.positiveBg,
            borderRadius: radius.md,
            padding: spacing.md,
            gap: spacing.xs,
          }}
        >
          <Text variant="bodyStrong" tone="positive">
            Order recorded
          </Text>
          <Text variant="caption" tone="secondary">
            {lastFill.side.toUpperCase()} {lastFill.qty} {symbol} @ {formatCurrency(lastFill.price)}
          </Text>
        </View>
      ) : null}
    </Card>
  );
}
