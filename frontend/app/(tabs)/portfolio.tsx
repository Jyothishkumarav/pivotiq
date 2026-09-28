import React, { useMemo, useState } from "react";
import { Platform, Pressable, ScrollView, useWindowDimensions, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Screen, Segmented, Text } from "@/components/ui";
import { FyersConnectionCard } from "@/components/FyersLivePanel";
import { AutoTradeSettingsCard } from "@/components/AutoTradeSettingsCard";
import { BrokerFundsCard } from "@/components/BrokerFundsCard";
import { OrdersBookCard } from "@/components/OrdersBookCard";
import { QuickTradeModal } from "@/components/QuickTradeModal";
import { tradingApi } from "@/api/trading";
import { colors, layout, radius, spacing } from "@/theme/tokens";
import { formatCurrency, formatPercent, formatRelativeTime } from "@/utils/format";
import { BrokerType, Position, Segment } from "@/types";

interface TradingDay {
  iso: string;
  label: string;
  shortLabel: string;
  dayOfWeek: string;
  isToday: boolean;
}

function getRecentTradingDays(maxDays = 30): TradingDay[] {
  const days: TradingDay[] = [];
  const now = new Date();
  const curr = new Date(now);
  let checked = 0;

  while (days.length < maxDays && checked < 60) {
    const dayOfWeek = curr.getDay(); // 0 = Sun, 6 = Sat
    if (dayOfWeek !== 0 && dayOfWeek !== 6) {
      const year = curr.getFullYear();
      const month = String(curr.getMonth() + 1).padStart(2, "0");
      const date = String(curr.getDate()).padStart(2, "0");
      const iso = `${year}-${month}-${date}`;

      const isToday =
        iso ===
        `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

      const dayName = dayNames[dayOfWeek];
      const monthName = monthNames[curr.getMonth()];

      days.push({
        iso,
        label: isToday ? "Today" : `${dayName} ${curr.getDate()} ${monthName}`,
        shortLabel: isToday ? "Today" : `${curr.getDate()} ${monthName}`,
        dayOfWeek: dayName,
        isToday,
      });
    }
    curr.setDate(curr.getDate() - 1);
    checked++;
  }
  return days;
}

function DateSelector({
  value,
  onChange,
  days,
}: {
  value: string | null;
  onChange: (date: string | null) => void;
  days: TradingDay[];
}) {
  return (
    <View style={{ gap: spacing.xs, marginTop: spacing.xs }}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text variant="caption" tone="muted" style={{ textTransform: "uppercase", letterSpacing: 1, fontWeight: "600" }}>
          📅 Session / Retest Mode (30 Days)
        </Text>
        {value ? (
          <Pressable onPress={() => onChange(null)}>
            <Text variant="caption" tone="accent" style={{ fontWeight: "700" }}>
              ⚡ Back to Live
            </Text>
          </Pressable>
        ) : null}
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 6, paddingVertical: 2 }}
      >
        {/* Live / Today pill */}
        <Pressable
          onPress={() => onChange(null)}
          style={({ hovered }: any) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: 5,
            paddingHorizontal: spacing.md,
            paddingVertical: 6,
            borderRadius: 8,
            borderWidth: 1.5,
            borderColor: value === null ? colors.positive : hovered ? colors.border : colors.borderSubtle,
            backgroundColor:
              value === null
                ? "rgba(61,219,159,0.12)"
                : hovered
                  ? colors.surfaceElevated
                  : "transparent",
          })}
        >
          <Text style={{ fontSize: 12 }}>⚡</Text>
          <Text
            variant="caption"
            style={{
              fontWeight: value === null ? "700" : "500",
              color: value === null ? colors.positive : colors.textSecondary,
            }}
          >
            Live (Today)
          </Text>
        </Pressable>

        {/* Historical trading days */}
        {days.map((d) => {
          const selected = value === d.iso;
          return (
            <Pressable
              key={d.iso}
              onPress={() => onChange(d.iso)}
              style={({ hovered }: any) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 5,
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
                borderRadius: 8,
                borderWidth: 1.5,
                borderColor: selected ? "#F5B54A" : hovered ? colors.border : colors.borderSubtle,
                backgroundColor: selected
                  ? "rgba(245,181,74,0.15)"
                  : hovered
                    ? colors.surfaceElevated
                    : "transparent",
              })}
            >
              <Text
                variant="caption"
                style={{
                  fontWeight: selected ? "700" : "500",
                  color: selected ? "#F5B54A" : colors.textSecondary,
                }}
              >
                {d.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const SEGMENT_OPTIONS = [
  { value: "intraday" as Segment, label: "Intraday (MIS)" },
  { value: "delivery" as Segment, label: "Delivery (CNC)" },
];

const VIEW_TABS = [
  { value: "positions", label: "Positions" },
  { value: "orders", label: "Orders Book" },
  { value: "autotrade", label: "Auto-Trade (Config)" },
];

type SortKey = "time" | "symbol" | "qty" | "avg" | "ltp" | "dayChange" | "pnl";
type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

const HOLDING_COLUMNS: { key: SortKey; label: string; flex: number; align: "flex-start" | "flex-end" }[] = [
  { key: "time", label: "Entry / Symbol", flex: 2, align: "flex-start" },
  { key: "qty", label: "Qty", flex: 0.6, align: "flex-end" },
  { key: "avg", label: "Avg", flex: 1, align: "flex-end" },
  { key: "ltp", label: "LTP", flex: 1, align: "flex-end" },
  { key: "dayChange", label: "Day", flex: 0.9, align: "flex-end" },
  { key: "pnl", label: "P&L", flex: 1.4, align: "flex-end" },
];

const HOLDING_EXTRACTORS: Record<SortKey, (p: Position) => string | number> = {
  time: (p) => p.firstBoughtAt || "",
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
      onChange({ key, dir: key === "time" ? "asc" : "desc" });
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
  linkedSl,
  onClose,
  isClosing,
  readOnly = false,
}: {
  position: Position;
  linkedSl?: number | null;
  onClose: () => void;
  isClosing: boolean;
  readOnly?: boolean;
}) {
  const isUp = position.pnl >= 0;
  const isDayUp = position.dayChangePercent >= 0;
  const changePct = position.avgPrice > 0 ? ((position.ltp - position.avgPrice) / position.avgPrice) * 100 : 0;
  const boughtIso = position.firstBoughtAt
    ? position.firstBoughtAt.endsWith("Z") || position.firstBoughtAt.includes("+")
      ? position.firstBoughtAt
      : position.firstBoughtAt + "Z"
    : null;
  const boughtDate = boughtIso
    ? new Date(boughtIso).toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        timeZone: "Asia/Kolkata",
      })
    : null;
  const boughtTime = boughtIso
    ? new Date(boughtIso).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
        timeZone: "Asia/Kolkata",
      })
    : null;

  const isClosed = position.netQty === 0;

  return (
    <Card
      padded={false}
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.md,
        borderLeftWidth: 3,
        borderLeftColor: isClosed ? (isUp ? colors.positive : colors.negative) : isUp ? colors.positive : colors.negative,
        opacity: isClosing ? 0.5 : isClosed ? 0.8 : 1,
      }}
    >
      <View style={{ flex: 2, gap: 2 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
          <Text variant="subtitle">{position.symbol}</Text>
          <Badge label={position.segment === "intraday" ? "MIS" : "CNC"} tone="neutral" />
          <Badge
            label={isClosed ? "CLOSED (SL HIT)" : position.netQty > 0 ? "BUY" : "SELL / SHORT"}
            tone={isClosed ? "warning" : position.netQty > 0 ? "positive" : "negative"}
          />
          {linkedSl && !isClosed ? (
            <Badge label={`SL ₹${linkedSl}`} tone="warning" />
          ) : null}
        </View>
        {boughtDate ? (
          <Text variant="caption" tone="muted">
            {isClosed ? "Exited" : position.netQty > 0 ? "Bought" : "Shorted"} {boughtDate} · {boughtTime}
          </Text>
        ) : null}
      </View>

      <View style={{ flex: 0.6, alignItems: "flex-end" }}>
        <Text variant="mono" tone={isClosed ? "muted" : undefined}>
          {isClosed ? "0" : Math.abs(position.netQty)}
        </Text>
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
        {readOnly ? (
          <Text variant="caption" tone="muted" style={{ fontSize: 11 }}>
            Locked
          </Text>
        ) : isClosed ? (
          <Text variant="caption" tone="muted" style={{ fontSize: 11, fontWeight: "600" }}>
            CLOSED
          </Text>
        ) : (
          <ClosePositionButton onPress={onClose} disabled={isClosing} />
        )}
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
            ? window.confirm("Square off this position? Market exit order will be executed and any linked SL orders cancelled.")
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

function SummaryHero({ segment, broker, date }: { segment: Segment; broker: BrokerType; date?: string | null }) {
  const { data } = useQuery({
    queryKey: ["portfolio-summary", segment, broker, date],
    queryFn: () => tradingApi.portfolioSummary(segment, broker, date),
    refetchInterval: 5000,
  });

  if (!data) return null;
  const isUp = data.pnl >= 0;
  const isDayUp = data.todayPnl >= 0;

  return (
    <Card elevated style={{ gap: spacing.md }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <Text variant="caption" tone="secondary" style={{ textTransform: "uppercase", letterSpacing: 1.5 }}>
            {segment === "intraday" ? "Intraday (MIS)" : "Delivery (CNC)"}
          </Text>
          <Badge label={broker === "fyers" ? "Fyers Live" : "Paper Sandbox"} tone={broker === "fyers" ? "positive" : "neutral"} />
        </View>
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
              Today P&L
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

  const [broker, setBroker] = useState<BrokerType>("paper");
  const [retestDate, setRetestDate] = useState<string | null>(null);
  const tradingDays = useMemo(() => getRecentTradingDays(30), []);
  const [activeTab, setActiveTab] = useState<string>("positions");
  const [segment, setSegment] = useState<Segment>("intraday");
  const [sort, setSort] = useState<SortState>({ key: "time", dir: "asc" });
  const [refreshedAt, setRefreshedAt] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [quickTradeOpen, setQuickTradeOpen] = useState(false);

  const {
    data: positions,
    isLoading,
    error: positionsError,
    refetch: refetchPositions,
  } = useQuery({
    queryKey: ["positions", segment, broker, retestDate],
    queryFn: () => tradingApi.positions(segment, broker, retestDate),
    refetchInterval: 5000,
  });

  const { data: openOrders } = useQuery({
    queryKey: ["trades-orders", broker, retestDate],
    queryFn: () => tradingApi.listOrders(broker, retestDate),
    refetchInterval: 10000,
  });

  const closeMutation = useMutation({
    mutationFn: (p: Position) =>
      tradingApi.exitPosition({
        symbol: p.symbol,
        broker,
        strategy: "portfolio_manual",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
      queryClient.invalidateQueries({ queryKey: ["trades-orders"] });
      queryClient.invalidateQueries({ queryKey: ["trades-funds"] });
    },
  });

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["trades-orders"] }),
        queryClient.invalidateQueries({ queryKey: ["trades-funds"] }),
      ]);
      setRefreshedAt(new Date());
    } finally {
      setIsRefreshing(false);
    }
  };

  const filteredPositions = positions ?? [];
  const sortedPositions = sortHoldings(filteredPositions, sort);

  const pendingOrdersCount = (openOrders || []).filter(
    (o) => o.status === "open"
  ).length;

  const dynamicTabs = [
    { value: "positions", label: "Positions" },
    { value: "orders", label: `Orders Book${pendingOrdersCount > 0 ? ` (${pendingOrdersCount})` : ""}` },
    { value: "autotrade", label: "Auto-Trade (Config)" },
  ];

  return (
    <Screen width="wide">
      {/* Header & Broker Switcher */}
      <View
        style={{
          flexDirection: twoColumn ? "row" : "column",
          justifyContent: "space-between",
          alignItems: twoColumn ? "flex-end" : "flex-start",
          gap: spacing.md,
        }}
      >
        <View style={{ gap: spacing.xs, flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Text variant="display">Portfolio</Text>
            <Badge label="5x Leverage MIS" tone="neutral" />
            {retestDate ? <Badge label={`Historical: ${retestDate}`} tone="warning" /> : null}
          </View>
          <Text variant="body" tone="secondary">
            Multi-broker order execution, real-time risk sizing & strategy auto-trading.
          </Text>
        </View>

        <View style={{ alignItems: twoColumn ? "flex-end" : "flex-start", gap: spacing.sm }}>
          {/* Broker Selector Pills */}
          <View style={{ flexDirection: "row", gap: spacing.xs, backgroundColor: colors.surfaceElevated, padding: 4, borderRadius: radius.md }}>
            <Pressable
              onPress={() => setBroker("paper")}
              style={{
                paddingVertical: 6,
                paddingHorizontal: 12,
                borderRadius: radius.sm,
                backgroundColor: broker === "paper" ? colors.accent : "transparent",
              }}
            >
              <Text
                variant="caption"
                style={{
                  color: broker === "paper" ? "#000" : colors.textSecondary,
                  fontWeight: "700",
                }}
              >
                Paper Sandbox
              </Text>
            </Pressable>

            <Pressable
              onPress={() => setBroker("fyers")}
              style={{
                paddingVertical: 6,
                paddingHorizontal: 12,
                borderRadius: radius.sm,
                backgroundColor: broker === "fyers" ? colors.positive : "transparent",
              }}
            >
              <Text
                variant="caption"
                style={{
                  color: broker === "fyers" ? "#000" : colors.textSecondary,
                  fontWeight: "700",
                }}
              >
                Fyers Live (MIS)
              </Text>
            </Pressable>
          </View>

          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Button label={isRefreshing ? "Refreshing…" : "Refresh"} onPress={handleRefresh} loading={isRefreshing} size="sm" variant="ghost" />
            <Text variant="caption" tone="muted">
              Refreshed {formatRelativeTime(refreshedAt.toISOString())}
            </Text>
          </View>
        </View>
      </View>

      {/* Date Selector for Session / Retest Mode */}
      <DateSelector value={retestDate} onChange={setRetestDate} days={tradingDays} />

      {/* Historical Retest Banner */}
      {retestDate && (
        <Card
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: spacing.md,
            paddingVertical: spacing.md,
            paddingHorizontal: spacing.lg,
            borderLeftWidth: 4,
            borderLeftColor: "#F5B54A",
            backgroundColor: "rgba(245,181,74,0.08)",
          }}
        >
          <View style={{ gap: 2, flex: 1, minWidth: 260 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              <Text variant="subtitle" style={{ color: "#F5B54A" }}>
                📅 Retest Mode · {tradingDays.find((d) => d.iso === retestDate)?.label || retestDate}
              </Text>
              <Badge label="Read-Only Session" tone="warning" />
            </View>
            <Text variant="caption" tone="muted">
              Displaying simulated order executions & positions for {retestDate}. Capital reset to ₹1,00,000 for this session.
            </Text>
          </View>
          <Button
            label="⚡ Back to Live (Today)"
            size="sm"
            variant="secondary"
            onPress={() => setRetestDate(null)}
          />
        </Card>
      )}

      {/* Fyers OAuth Connection Panel */}
      <FyersConnectionCard />

      {/* Broker Funds & 5x Buying Power Card */}
      <BrokerFundsCard broker={broker} onOpenQuickTrade={() => setQuickTradeOpen(true)} date={retestDate} />

      {/* Main Feature Tabs */}
      <View style={{ flexDirection: "row", gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.borderSubtle, paddingBottom: spacing.xs }}>
        {dynamicTabs.map((tab) => {
          const active = activeTab === tab.value;
          return (
            <Pressable
              key={tab.value}
              onPress={() => setActiveTab(tab.value)}
              style={{
                paddingVertical: spacing.sm,
                paddingHorizontal: spacing.md,
                borderBottomWidth: 2,
                borderBottomColor: active ? colors.accent : "transparent",
              }}
            >
              <Text variant="bodyStrong" tone={active ? "accent" : "muted"}>
                {tab.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Active Tab Content */}
      {activeTab === "positions" && (
        <View style={{ gap: spacing.lg }}>
          <Segmented value={segment} options={SEGMENT_OPTIONS} onChange={setSegment} />
          <SummaryHero segment={segment} broker={broker} date={retestDate} />

          <View style={{ gap: spacing.md }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text variant="title">
                {retestDate ? `Positions (${tradingDays.find((d) => d.iso === retestDate)?.shortLabel || retestDate})` : "Open Positions"}
              </Text>
              <Text variant="caption" tone="muted">
                {filteredPositions.length} · sorted by {HOLDING_COLUMNS.find((c) => c.key === sort.key)?.label} ({sort.dir === "asc" ? "asc" : "desc"})
              </Text>
            </View>

            {isLoading ? (
              <LoadingBlock label="Loading holdings…" compact />
            ) : positionsError ? (
              <Card
                style={{
                  alignItems: "center",
                  gap: spacing.sm,
                  padding: spacing.xl,
                  borderWidth: 1,
                  borderColor: colors.negative,
                  backgroundColor: colors.negativeBg,
                }}
              >
                <Text variant="subtitle" tone="negative">Failed to load positions</Text>
                <Text variant="caption" tone="secondary" style={{ textAlign: "center" }}>
                  {(positionsError as Error)?.message || "Network error while connecting to trading engine."}
                </Text>
                <Button label="Retry" size="sm" variant="secondary" onPress={() => refetchPositions()} />
              </Card>
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
                <Text variant="subtitle">No positions on {broker === "fyers" ? "Fyers" : "Paper"}{retestDate ? ` for ${retestDate}` : ""}</Text>
                <Text variant="caption" tone="secondary" style={{ textAlign: "center" }}>
                  {retestDate
                    ? "No simulated trades were triggered on this historical date."
                    : "Launch a quick trade or enable auto-trading for strategies to execute orders automatically."}
                </Text>
                {!retestDate && (
                  <Button label="+ Place Buy + SL Order" size="sm" onPress={() => setQuickTradeOpen(true)} />
                )}
              </Card>
            ) : (
              <View style={{ gap: spacing.xs }}>
                <HoldingsHeader state={sort} onChange={setSort} />
                {sortedPositions.map((p) => {
                  const slOrder = (openOrders || []).find(
                    (o) =>
                      o.symbol === p.symbol &&
                      o.status === "open" &&
                      (o.order_type === "sl_m" || o.order_type === "sl_l" || o.purpose === "stop_loss")
                  );
                  const activeSlPrice = slOrder?.stop_price || slOrder?.price || null;
                  return (
                    <HoldingRow
                      key={`${p.symbol}-${p.segment}`}
                      position={p}
                      linkedSl={activeSlPrice}
                      readOnly={!!retestDate}
                      onClose={() => closeMutation.mutate(p)}
                      isClosing={closeMutation.isPending && closeMutation.variables?.symbol === p.symbol}
                    />
                  );
                })}
              </View>
            )}
          </View>
        </View>
      )}

      {activeTab === "orders" && (
        <OrdersBookCard broker={broker} date={retestDate} />
      )}

      {activeTab === "autotrade" && (
        <AutoTradeSettingsCard />
      )}

      {/* Quick Trade Buy + SL Modal */}
      <QuickTradeModal
        visible={quickTradeOpen}
        onClose={() => setQuickTradeOpen(false)}
        activeBroker={broker}
      />
    </Screen>
  );
}
