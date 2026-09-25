import React, { useState } from "react";
import { Pressable, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Text } from "@/components/ui";
import { tradingApi } from "@/api/trading";
import { colors, radius, spacing } from "@/theme/tokens";
import { formatCurrency, formatOrderTimestamp } from "@/utils/format";
import { BrokerOrder } from "@/types";

interface Props {
  broker: string;
  date?: string | null;
}

type OrderFilter = "all" | "entry" | "sl" | "open";
type SortDirection = "first_entry_last" | "first_entry_first";

export function OrdersBookCard({ broker, date }: Props) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<OrderFilter>("all");
  const [sortDir, setSortDir] = useState<SortDirection>("first_entry_last");

  const { data: orders, isLoading, isRefetching, refetch } = useQuery({
    queryKey: ["trades-orders", broker, date],
    queryFn: () => tradingApi.listOrders(broker, date),
    refetchInterval: 10000,
  });

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) => tradingApi.cancelOrder(orderId, broker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades-orders", broker] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
    },
  });

  const rawList = orders || [];

  const isOrderSL = (o: BrokerOrder) =>
    o.purpose === "stop_loss" || o.order_type === "sl_m" || o.order_type === "sl_l";

  // Filter calculations
  const entryCount = rawList.filter((o) => o.purpose === "entry" && !isOrderSL(o)).length;
  const slCount = rawList.filter(isOrderSL).length;
  const openCount = rawList.filter((o) => o.status === "open").length;

  const filteredOrders = rawList.filter((order) => {
    if (filter === "entry") return order.purpose === "entry" && !isOrderSL(order);
    if (filter === "sl") return isOrderSL(order);
    if (filter === "open") return order.status === "open";
    return true;
  });

  // Sort: Default is first_entry_last (newest on top, earliest/first entry of the session at the bottom)
  const sortedOrders = [...filteredOrders].sort((a, b) => {
    const parseTime = (iso: string) => {
      const normalized = iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`;
      return new Date(normalized).getTime();
    };

    const timeA = parseTime(a.placed_at);
    const timeB = parseTime(b.placed_at);

    if (timeA !== timeB) {
      return sortDir === "first_entry_last" ? timeB - timeA : timeA - timeB;
    }

    // Tie-breaker for same timestamp: group by symbol
    if (a.symbol !== b.symbol) {
      return a.symbol.localeCompare(b.symbol);
    }

    // Within same symbol: ENTRY always precedes SL
    const getRank = (o: BrokerOrder) => {
      if (o.purpose === "entry" && !isOrderSL(o)) return 1;
      if (isOrderSL(o)) return 2;
      return 3;
    };
    return getRank(a) - getRank(b);
  });

  const filterTabs: { id: OrderFilter; label: string }[] = [
    { id: "all", label: `All (${rawList.length})` },
    { id: "entry", label: `ENTRY (${entryCount})` },
    { id: "sl", label: `SL (${slCount})` },
    ...(openCount > 0 ? [{ id: "open" as OrderFilter, label: `Open (${openCount})` }] : []),
  ];

  return (
    <Card elevated style={{ gap: spacing.md }}>
      {/* Header */}
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: spacing.sm }}>
        <View style={{ gap: 2 }}>
          <Text variant="title">Orders Book</Text>
          <Text variant="caption" tone="muted">
            {rawList.length} order{rawList.length === 1 ? "" : "s"} {date ? `on ${date}` : "placed today"} · {broker === "fyers" ? "Fyers Live" : "Paper Sandbox"}
          </Text>
        </View>

        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <Pressable
            onPress={() =>
              setSortDir((prev) =>
                prev === "first_entry_last" ? "first_entry_first" : "first_entry_last"
              )
            }
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: spacing.sm,
              paddingVertical: 5,
              borderRadius: radius.sm,
              backgroundColor: colors.surfaceHover,
              borderWidth: 1,
              borderColor: colors.border,
            }}
          >
            <Text variant="caption" tone="secondary" style={{ fontSize: 11, fontWeight: "600" }}>
              {sortDir === "first_entry_last" ? "⏱ First Entry at Last ↓" : "⏱ First Entry at Top ↑"}
            </Text>
          </Pressable>

          <Button
            label={isRefetching ? "Refreshing…" : "Refresh"}
            variant="ghost"
            size="sm"
            onPress={() => refetch()}
          />
        </View>
      </View>

      {/* Filter Chips Bar */}
      <View style={{ flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" }}>
        {filterTabs.map((tab) => {
          const isActive = filter === tab.id;
          return (
            <Pressable
              key={tab.id}
              onPress={() => setFilter(tab.id)}
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: 5,
                borderRadius: radius.full,
                backgroundColor: isActive ? colors.accent : colors.surfaceHover,
                borderWidth: 1,
                borderColor: isActive ? colors.accent : colors.border,
              }}
            >
              <Text
                variant="caption"
                style={{
                  fontSize: 11,
                  fontWeight: isActive ? "700" : "500",
                  color: isActive ? "#ffffff" : colors.textSecondary,
                }}
              >
                {tab.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Content */}
      {isLoading ? (
        <LoadingBlock label="Loading orders…" compact />
      ) : sortedOrders.length === 0 ? (
        <Card
          padded={false}
          style={{
            alignItems: "center",
            padding: spacing.xl,
            borderStyle: "dashed",
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: radius.md,
            gap: spacing.xs,
          }}
        >
          <Text variant="body" tone="secondary">
            {filter === "all" ? "No orders found" : `No ${filter.toUpperCase()} orders found`}
          </Text>
          <Text variant="caption" tone="muted">
            {filter === "all"
              ? "Orders triggered by strategies or placed manually will appear here."
              : `Change filter to view other orders.`}
          </Text>
        </Card>
      ) : (
        <View style={{ gap: spacing.xs }}>
          {sortedOrders.map((order) => {
            const isBuy = order.side === "buy";
            const isOpen = order.status === "open";
            const isFilled = order.status === "filled";
            const isRejected = order.status === "rejected";

            const statusTone = isFilled
              ? "positive"
              : isOpen
              ? "warning"
              : isRejected
              ? "negative"
              : "neutral";

            const isSL = isOrderSL(order);
            const isExit = order.purpose === "exit";

            // Left indicator: warning amber for SL, green for Buy entry, red for Sell entry
            const borderIndicatorColor = isSL
              ? colors.warning
              : isBuy
              ? colors.positive
              : colors.negative;

            return (
              <Card
                key={order.order_id}
                padded={false}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                  backgroundColor: colors.surfaceElevated,
                  borderLeftWidth: 3,
                  borderLeftColor: borderIndicatorColor,
                }}
              >
                {/* Symbol, Side, Purpose & Timestamp */}
                <View style={{ flex: 2.2, gap: 2 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
                    <Text variant="bodyStrong">{order.symbol}</Text>
                    <Badge
                      label={isBuy ? "BUY" : "SELL"}
                      tone={isBuy ? "positive" : "negative"}
                    />
                    <Badge
                      label={isSL ? "SL" : isExit ? "EXIT" : "ENTRY"}
                      tone={isSL ? "warning" : "neutral"}
                    />
                  </View>
                  <Text variant="caption" tone="muted" style={{ fontSize: 11 }}>
                    {formatOrderTimestamp(order.placed_at)} · {order.order_type.toUpperCase()}
                  </Text>
                </View>

                {/* Quantity */}
                <View style={{ flex: 0.9, alignItems: "flex-end" }}>
                  <Text variant="caption" tone="muted">Qty</Text>
                  <Text variant="mono">{order.filled_qty ? `${order.filled_qty}/${order.qty}` : order.qty}</Text>
                </View>

                {/* Price / Trigger Price */}
                <View style={{ flex: 1.3, alignItems: "flex-end" }}>
                  <Text variant="caption" tone="muted">
                    {isSL ? "SL Trigger" : "Exec Price"}
                  </Text>
                  <Text variant="mono" style={{ fontWeight: "600" }}>
                    {isSL && order.stop_price
                      ? formatCurrency(order.stop_price)
                      : order.price
                      ? formatCurrency(order.price)
                      : "MKT"}
                  </Text>
                </View>

                {/* Status & Cancel Action */}
                <View style={{ flex: 1.2, alignItems: "flex-end", gap: 4 }}>
                  <Badge label={order.status.toUpperCase()} tone={statusTone} />
                  {isOpen && (
                    <Pressable
                      onPress={() => cancelMutation.mutate(order.order_id)}
                      disabled={cancelMutation.isPending}
                      style={{
                        paddingHorizontal: 8,
                        paddingVertical: 2,
                        borderRadius: 4,
                        borderWidth: 1,
                        borderColor: colors.negative,
                        backgroundColor: colors.negativeBg,
                      }}
                    >
                      <Text variant="caption" tone="negative" style={{ fontSize: 10, fontWeight: "600" }}>
                        CANCEL
                      </Text>
                    </Pressable>
                  )}
                </View>
              </Card>
            );
          })}
        </View>
      )}
    </Card>
  );
}
