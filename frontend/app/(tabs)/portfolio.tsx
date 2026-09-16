import React, { useState } from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Screen, Segmented, Text } from "@/components/ui";
import { FyersConnectionCard } from "@/components/FyersLivePanel";
import { tradingApi } from "@/api/trading";
import { colors, layout, radius, spacing } from "@/theme/tokens";
import { formatCurrency, formatPercent, formatRelativeTime } from "@/utils/format";
import { Position, Segment } from "@/types";

const SEGMENT_OPTIONS = [
  { value: "intraday" as Segment, label: "Intraday (MIS)" },
  { value: "delivery" as Segment, label: "Delivery (CNC)" },
];

type SortKey = "symbol" | "qty" | "avg" | "ltp" | "dayChange" | "pnl";
type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

const HOLDING_COLUMNS: { key: SortKey; label: string; flex: number; align: "flex-start" | "flex-end" }[] = [
  { key: "symbol", label: "Symbol", flex: 2, align: "flex-start" },
  { key: "qty", label: "Qty", flex: 0.6, align: "flex-end" },
  { key: "avg", label: "Avg", flex: 1, align: "flex-end" },
  { key: "ltp", label: "LTP", flex: 1, align: "flex-end" },
  { key: "dayChange", label: "Day", flex: 0.9, align: "flex-end" },
  { key: "pnl", label: "P&L", flex: 1.4, align: "flex-end" },
];

const HOLDING_EXTRACTORS: Record<SortKey, (p: Position) => string | number> = {
  symbol: (p) => p.symbol,
  qty: (p) => p.netQty,
  avg: (p) => p.avgPrice,
  ltp: (p) => p.ltp,
  dayChange: (p) => p.dayChangePercent,
  pnl: (p) => p.pnl,
};

function sortHoldings(items: Position[], state: SortState): Position[] {
  const extract = HOLDING_EXTRACTORS[state.key];
  const sign = state.dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const va = extract(a);
    const vb = extract(b);
    if (typeof va === "string" && typeof vb === "string") return sign * va.localeCompare(vb);
    return sign * (Number(va) - Number(vb));
  });
}

function HoldingsHeader({ state, onChange }: { state: SortState; onChange: (next: SortState) => void }) {
  const cycle = (key: SortKey) => {
    if (state.key === key) {
      onChange({ key, dir: state.dir === "asc" ? "desc" : "asc" });
    } else {
      onChange({ key, dir: key === "symbol" ? "asc" : "desc" });
    }
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.sm,
      }}
    >
      {HOLDING_COLUMNS.map((col) => {
        const active = state.key === col.key;
        return (
          <Pressable
            key={col.key}
            onPress={() => cycle(col.key)}
            style={({ hovered }: any) => ({
              flex: col.flex,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: col.align === "flex-end" ? "flex-end" : "flex-start",
              gap: 6,
              paddingHorizontal: spacing.xs,
              paddingVertical: 2,
              borderRadius: 4,
              backgroundColor: hovered ? colors.surfaceElevated : "transparent",
            })}
          >
            <Text
              variant="caption"
              tone={active ? "accent" : "muted"}
              style={{ textTransform: "uppercase", letterSpacing: 1 }}
            >
              {col.label}
            </Text>
            {active ? (
              <Text variant="caption" tone="accent" style={{ fontSize: 9, lineHeight: 12 }}>
                {state.dir === "asc" ? "▲" : "▼"}
              </Text>
            ) : null}
          </Pressable>
        );
      })}
      <View style={{ width: 42 }} />
    </View>
  );
}

function HoldingRow({
  position,
  onClose,
  isClosing,
}: {
  position: Position;
  onClose: () => void;
  isClosing: boolean;
}) {
  const isUp = position.pnl >= 0;
  const isDayUp = position.dayChangePercent >= 0;
  const changePct = position.avgPrice > 0 ? ((position.ltp - position.avgPrice) / position.avgPrice) * 100 : 0;
  const boughtDate = position.firstBoughtAt
    ? new Date(position.firstBoughtAt).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
    : null;

  return (
    <Card
      padded={false}
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.md,
        borderLeftWidth: 3,
        borderLeftColor: isUp ? colors.positive : colors.negative,
        opacity: isClosing ? 0.5 : 1,
      }}
    >
      <View style={{ flex: 2, gap: 2 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <Text variant="subtitle">{position.symbol}</Text>
          <Badge label={position.segment === "intraday" ? "MIS" : "CNC"} tone="neutral" />
        </View>
        {boughtDate ? (
          <Text variant="caption" tone="muted">
            Bought {boughtDate} · {formatRelativeTime(position.firstBoughtAt!)}
          </Text>
        ) : null}
      </View>

      <View style={{ flex: 0.6, alignItems: "flex-end" }}>
        <Text variant="mono">{position.netQty}</Text>
      </View>

      <View style={{ flex: 1, alignItems: "flex-end" }}>
        <Text variant="mono">{formatCurrency(position.avgPrice)}</Text>
      </View>

      <View style={{ flex: 1, alignItems: "flex-end" }}>
        <Text variant="mono">{formatCurrency(position.ltp)}</Text>
      </View>

      <View style={{ flex: 0.9, alignItems: "flex-end" }}>
        <Text variant="mono" tone={isDayUp ? "positive" : "negative"}>
          {formatPercent(position.dayChangePercent)}
        </Text>
      </View>

      <View style={{ flex: 1.4, alignItems: "flex-end", gap: 2 }}>
        <Text variant="mono" tone={isUp ? "positive" : "negative"}>
          {isUp ? "+" : "−"}
          {formatCurrency(Math.abs(position.pnl))}
        </Text>
        <Text variant="caption" tone={isUp ? "positive" : "negative"}>
          {formatPercent(changePct)}
        </Text>
      </View>

      <View style={{ width: 42, alignItems: "flex-end" }}>
        <ClosePositionButton onPress={onClose} disabled={isClosing} />
      </View>
    </Card>
  );
}

function ClosePositionButton({ onPress, disabled }: { onPress: () => void; disabled: boolean }) {
  return (
    <Pressable
      onPress={(e: any) => {
        e?.stopPropagation?.();
        if (Platform.OS === "web") {
          const ok = typeof window !== "undefined"
            ? window.confirm("Close this position? A market sell will be placed for the full quantity.")
            : true;
          if (!ok) return;
        }
        onPress();
      }}
      disabled={disabled}
      hitSlop={8}
      style={({ hovered }: any) => ({
        width: 30,
        height: 30,
        borderRadius: radius.full,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: hovered ? colors.negativeBg : "transparent",
        borderWidth: 1,
        borderColor: hovered ? colors.negative : colors.borderSubtle,
        opacity: disabled ? 0.4 : 1,
      })}
    >
      <Text
        variant="bodyStrong"
        style={{ color: colors.textSecondary, lineHeight: 18, fontSize: 16 }}
      >
        ×
      </Text>
    </Pressable>
  );
}

function SummaryHero({ segment }: { segment: Segment }) {
  const { data } = useQuery({
    queryKey: ["portfolio-summary", segment],
    queryFn: () => tradingApi.portfolioSummary(segment),
  });

  if (!data) return null;
  const isUp = data.pnl >= 0;
  const isDayUp = data.todayPnl >= 0;

  return (
    <Card elevated style={{ gap: spacing.md }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" }}>
        <Text variant="caption" tone="secondary" style={{ textTransform: "uppercase", letterSpacing: 1.5 }}>
          {segment === "intraday" ? "Intraday (MIS)" : "Delivery (CNC)"}
        </Text>
        <Text variant="caption" tone="muted">
          {data.holdingsCount} holding{data.holdingsCount === 1 ? "" : "s"}
        </Text>
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
        <View style={{ gap: 2, flex: 1, minWidth: 180 }}>
          <Text variant="caption" tone="muted">
            Current value
          </Text>
          <Text variant="title" style={{ fontSize: 22, letterSpacing: -0.3 }}>
            {formatCurrency(data.currentValue)}
          </Text>
          <Text variant="caption" tone={isUp ? "positive" : "negative"}>
            {isUp ? "▲" : "▼"} {formatCurrency(Math.abs(data.pnl))} ({formatPercent(data.pnlPercent)})
          </Text>
        </View>

        <View style={{ gap: spacing.xs, minWidth: 160 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.md }}>
            <Text variant="caption" tone="muted">
              Invested
            </Text>
            <Text variant="mono">{formatCurrency(data.investedValue)}</Text>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.md }}>
            <Text variant="caption" tone="muted">
              Today
            </Text>
            <Text variant="mono" tone={isDayUp ? "positive" : "negative"}>
              {formatCurrency(data.todayPnl)}
            </Text>
          </View>
        </View>
      </View>
    </Card>
  );
}

export default function PortfolioScreen() {
  const queryClient = useQueryClient();
  const { width } = useWindowDimensions();
  const twoColumn = Platform.OS === "web" && width >= layout.wideBreakpoint;

  const [segment, setSegment] = useState<Segment>("delivery");
  const [sort, setSort] = useState<SortState>({ key: "pnl", dir: "desc" });
  const [refreshedAt, setRefreshedAt] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);

  const { data: positions, isLoading } = useQuery({
    queryKey: ["positions", segment],
    queryFn: () => tradingApi.positions(segment),
  });

  const closeMutation = useMutation({
    mutationFn: (p: Position) =>
      tradingApi.placeTrade({
        symbol: p.symbol,
        segment: p.segment,
        side: "sell",
        qty: p.netQty,
        orderType: "market",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] }),
      ]);
      setRefreshedAt(new Date());
    } finally {
      setIsRefreshing(false);
    }
  };

  const filteredPositions = positions ?? [];
  const sortedPositions = sortHoldings(filteredPositions, sort);

  return (
    <Screen width="wide">
      <View
        style={{
          flexDirection: twoColumn ? "row" : "column",
          justifyContent: "space-between",
          alignItems: twoColumn ? "flex-end" : "flex-start",
          gap: spacing.md,
        }}
      >
        <View style={{ gap: spacing.xs, flex: 1 }}>
          <Text variant="display">Portfolio</Text>
          <Text variant="body" tone="secondary">
            Paper trading only. Connect Fyers below to use live prices instead of Yahoo.
          </Text>
        </View>
        <View style={{ alignItems: twoColumn ? "flex-end" : "flex-start", gap: spacing.xs }}>
          <Button label={isRefreshing ? "Refreshing…" : "Refresh prices"} onPress={handleRefresh} loading={isRefreshing} size="sm" />
          <Text variant="caption" tone="muted">
            Refreshed {formatRelativeTime(refreshedAt.toISOString())}
          </Text>
        </View>
      </View>

      <FyersConnectionCard />

      <Segmented value={segment} options={SEGMENT_OPTIONS} onChange={setSegment} />

      <SummaryHero segment={segment} />

      <View style={{ gap: spacing.md }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text variant="title">Holdings</Text>
          <Text variant="caption" tone="muted">
            {filteredPositions.length} · sorted by {HOLDING_COLUMNS.find((c) => c.key === sort.key)?.label} ({sort.dir === "asc" ? "asc" : "desc"})
          </Text>
        </View>

        {isLoading ? (
          <LoadingBlock label="Loading holdings…" compact />
        ) : sortedPositions.length === 0 ? (
          <Card
            style={{
              alignItems: "center",
              gap: spacing.sm,
              padding: spacing.xxl,
              borderStyle: "dashed",
              borderRadius: radius.lg,
            }}
          >
            <Text variant="subtitle">No holdings yet</Text>
            <Text variant="caption" tone="secondary" style={{ textAlign: "center" }}>
              Place a paper trade from a stock's detail screen to see it here.
            </Text>
          </Card>
        ) : (
          <View style={{ gap: spacing.xs }}>
            <HoldingsHeader state={sort} onChange={setSort} />
            {sortedPositions.map((p) => (
              <HoldingRow
                key={`${p.symbol}-${p.segment}`}
                position={p}
                onClose={() => closeMutation.mutate(p)}
                isClosing={closeMutation.isPending && closeMutation.variables?.symbol === p.symbol}
              />
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
}
