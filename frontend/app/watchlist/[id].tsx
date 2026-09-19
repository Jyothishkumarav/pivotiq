import React, { useEffect, useState } from "react";
import { Animated, Platform, Pressable, ScrollView, useWindowDimensions, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, LoadingBlock, Screen, Text } from "@/components/ui";
import { StockRow } from "@/components/StockRow";
import { StrategyAlertsModal } from "@/components/StrategyAlertsModal";
import { watchlistsApi } from "@/api/watchlists";
import { stocksApi } from "@/api/stocks";
import { settingsApi } from "@/api/settings";
import { colors, layout, spacing } from "@/theme/tokens";
import { WatchlistItem } from "@/types";

function openStock(symbol: string) {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    window.open(`/stock/${symbol}`, "_blank", "noopener,noreferrer");
    return;
  }
  return `/stock/${symbol}` as const;
}

type SortKey = "symbol" | "ltp" | "dayChange" | "support";
type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

const COLUMN_HEADERS: {
  key: SortKey;
  label: string;
  flex: number;
  align: "flex-start" | "flex-end";
  sortable?: boolean;
}[] = [
  { key: "symbol", label: "Symbol", flex: 1.4, align: "flex-start", sortable: true },
  { key: "ltp", label: "LTP", flex: 0.75, align: "flex-end", sortable: true },
  { key: "dayChange", label: "Day", flex: 0.7, align: "flex-end", sortable: true },
  { key: "symbol", label: "Setup", flex: 0.65, align: "flex-end", sortable: false },
  { key: "symbol", label: "Entry", flex: 0.85, align: "flex-end", sortable: false },
  { key: "symbol", label: "Stop Loss", flex: 1.45, align: "flex-end", sortable: false },
  { key: "symbol", label: "Status", flex: 0.65, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ Entry", flex: 0.7, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ SL", flex: 0.7, align: "flex-end", sortable: false },
  { key: "symbol", label: "Time", flex: 0.6, align: "flex-end", sortable: false },
  { key: "support", label: "Support", flex: 0.85, align: "flex-end", sortable: true },
];

/** Column value extractors. `null` values are always pushed to the end regardless of direction. */
const VALUE_EXTRACTORS: Record<SortKey, (i: WatchlistItem) => string | number | null> = {
  symbol: (i) => i.symbol,
  ltp: (i) => i.ltp,
  dayChange: (i) => i.changePercent,
  support: (i) => i.distanceToSupportPercent,
};

function sortItems(items: WatchlistItem[], state: SortState): WatchlistItem[] {
  const extract = VALUE_EXTRACTORS[state.key];
  const sign = state.dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const va = extract(a);
    const vb = extract(b);
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === "string" && typeof vb === "string") return sign * va.localeCompare(vb);
    return sign * (Number(va) - Number(vb));
  });
}

const INTRADAY_LEGEND: { glyph: string; color: string; label: string }[] = [
  { glyph: "▲", color: "#3DDB9F", label: "Above ORB (bullish)" },
  { glyph: "◆", color: "#9AA9C7", label: "Inside ORB (range)" },
  { glyph: "▼", color: "#FF6B85", label: "Below ORB (bearish)" },
];

const STRATEGY_OPTIONS: { value: string; label: string; icon: string; shortLabel: string }[] = [
  { value: "orb_vwap",            label: "ORB + VWAP",           icon: "⚡", shortLabel: "ORB + VWAP" },
  { value: "context_gated",       label: "Context-gated",         icon: "🛡️", shortLabel: "Context" },
  { value: "orb_pullback",        label: "ORB + VWAP Pullback",   icon: "🔄", shortLabel: "Pullback" },
  { value: "orb_pullback_support",label: "ORB + Pullback Support",icon: "🎯", shortLabel: "Support" },
];

const STRATEGY_COLORS: Record<string, { accent: string; glow: string; bg: string }> = {
  orb_vwap:             { accent: colors.accent,   glow: "rgba(91,139,255,0.25)",  bg: "rgba(91,139,255,0.10)" },
  context_gated:        { accent: "#9AA9C7",        glow: "rgba(154,169,199,0.20)", bg: "rgba(154,169,199,0.08)" },
  orb_pullback:         { accent: "#F5B54A",        glow: "rgba(245,181,74,0.22)",  bg: "rgba(245,181,74,0.09)" },
  orb_pullback_support: { accent: colors.positive, glow: "rgba(61,219,159,0.22)",  bg: "rgba(61,219,159,0.09)" },
};

function StrategyChip({
  option,
  active,
  loading,
  onPress,
}: {
  option: typeof STRATEGY_OPTIONS[number];
  active: boolean;
  loading: boolean;
  onPress: () => void;
}) {
  const palette = STRATEGY_COLORS[option.value] ?? {
    accent: colors.accent,
    glow: "rgba(91,139,255,0.25)",
    bg: "rgba(91,139,255,0.10)",
  };

  const webTransition = Platform.OS === "web"
    ? ({
        transition: "background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 120ms ease",
      } as any)
    : {};

  return (
    <Pressable
      onPress={() => !loading && !active && onPress()}
      disabled={loading || active}
      style={({ hovered, pressed }: any) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        paddingHorizontal: spacing.md,
        paddingVertical: 7,
        borderRadius: 999,
        borderWidth: 1.5,
        borderColor: active ? palette.accent : hovered ? colors.border : colors.borderSubtle,
        backgroundColor: active
          ? palette.bg
          : hovered
          ? colors.surfaceElevated
          : "transparent",
        opacity: loading && !active ? 0.55 : 1,
        ...webTransition,
        ...(Platform.OS === "web" && active
          ? { boxShadow: `0 0 0 3px ${palette.glow}, 0 0 14px ${palette.glow}` }
          : {}),
        ...(Platform.OS === "web" && !active && hovered
          ? { transform: [{ scale: 1.03 }] }
          : {}),
        ...(Platform.OS === "web" && pressed
          ? { transform: [{ scale: 0.97 }] }
          : {}),
      })}
    >
      {/* Strategy icon */}
      <Text style={{ fontSize: 13, lineHeight: 16 }}>{option.icon}</Text>

      {/* Label */}
      <Text
        variant="caption"
        style={{
          fontWeight: active ? "700" : "500",
          color: active ? palette.accent : colors.textSecondary,
          letterSpacing: 0.1,
          ...(Platform.OS === "web" ? { transition: "color 160ms ease, font-weight 160ms ease" } as any : {}),
        }}
      >
        {option.label}
      </Text>

      {/* Active dot indicator */}
      {active && (
        <View
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            backgroundColor: palette.accent,
            ...(Platform.OS === "web"
              ? ({ boxShadow: `0 0 6px ${palette.accent}` } as any)
              : {}),
          }}
        />
      )}
    </Pressable>
  );
}

function StrategySelector({
  value,
  onChange,
  loading,
}: {
  value: string;
  onChange: (strategy: string) => void;
  loading: boolean;
}) {
  return (
    <View
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        gap: spacing.sm,
        alignItems: "center",
      }}
    >
      {loading && (
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            backgroundColor: colors.accent,
            ...(Platform.OS === "web" ? ({ animation: "pulse 1s infinite" } as any) : {}),
          }}
        />
      )}
      {STRATEGY_OPTIONS.map((opt) => (
        <StrategyChip
          key={opt.value}
          option={opt}
          active={opt.value === value}
          loading={loading}
          onPress={() => onChange(opt.value)}
        />
      ))}
    </View>
  );
}

const ENTRY_MODE_STORAGE_KEY = "pivotiq:entry_mode";

function EntryModeToggle({
  value,
  onChange,
}: {
  value: "close" | "touch";
  onChange: (mode: "close" | "touch") => void;
}) {
  return (
    <View style={{ gap: 4, marginTop: 6 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
        <Text variant="caption" tone="secondary" style={{ fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Trigger on:
        </Text>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: colors.surfaceElevated,
            borderRadius: 8,
            padding: 3,
            borderWidth: 1,
            borderColor: colors.borderSubtle,
            gap: 4,
          }}
        >
          <Pressable
            onPress={() => onChange("close")}
            style={({ hovered }: any) => ({
              paddingHorizontal: spacing.md,
              paddingVertical: 6,
              borderRadius: 6,
              backgroundColor:
                value === "close"
                  ? colors.accent
                  : hovered
                    ? colors.surfaceHover
                    : "transparent",
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
            })}
          >
            <Text
              variant="caption"
              style={{
                fontWeight: "700",
                color: value === "close" ? "#FFFFFF" : colors.textSecondary,
                fontSize: 12,
              }}
            >
              🕯️ 3 Min Candle
            </Text>
          </Pressable>

          <Pressable
            onPress={() => onChange("touch")}
            style={({ hovered }: any) => ({
              paddingHorizontal: spacing.md,
              paddingVertical: 6,
              borderRadius: 6,
              backgroundColor:
                value === "touch"
                  ? colors.accent
                  : hovered
                    ? colors.surfaceHover
                    : "transparent",
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
            })}
          >
            <Text
              variant="caption"
              style={{
                fontWeight: "700",
                color: value === "touch" ? "#FFFFFF" : colors.textSecondary,
                fontSize: 12,
              }}
            >
              ⚡ Latest Price
            </Text>
          </Pressable>
        </View>
      </View>
      <Text variant="caption" tone="muted" style={{ fontSize: 11, lineHeight: 14 }}>
        {value === "close"
          ? "3 Min Candle: Confirms entry only after 3m candle closes beyond supporting candle (filters false wicks)"
          : "Latest Price: Triggers entry immediately on live price / wick breach"}
      </Text>
    </View>
  );
}

function IntradayLegend({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <View
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        alignItems: "center",
        gap: spacing.md,
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.xs,
      }}
    >
      <Text
        variant="caption"
        tone="muted"
        style={{ textTransform: "uppercase", letterSpacing: 1 }}
      >
        Intraday trend (first 20 min)
      </Text>
      {INTRADAY_LEGEND.map((entry) => (
        <View
          key={entry.glyph}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          <Text style={{ color: entry.color, fontSize: 11, lineHeight: 12 }}>
            {entry.glyph}
          </Text>
          <Text variant="caption" tone="secondary">
            {entry.label}
          </Text>
        </View>
      ))}
    </View>
  );
}

function SortableHeader({ state, onChange }: { state: SortState; onChange: (next: SortState) => void }) {
  const cycle = (key: SortKey) => {
    if (state.key === key) {
      onChange({ key, dir: state.dir === "asc" ? "desc" : "asc" });
    } else {
      // Support sort defaults to ascending (closest first). Others start descending
      // (highest LTP / biggest day gainer first), which feels most useful.
      onChange({ key, dir: key === "symbol" || key === "support" ? "asc" : "desc" });
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
      {COLUMN_HEADERS.map((col) => {
        const active = col.sortable !== false && state.key === col.key;
        const sortable = col.sortable !== false;
        return (
          <Pressable
            key={col.label}
            onPress={sortable ? () => cycle(col.key) : undefined}
            disabled={!sortable}
            style={({ hovered }: any) => ({
              flex: col.flex,
              alignItems: col.align,
              flexDirection: "row",
              justifyContent: col.align === "flex-end" ? "flex-end" : "flex-start",
              gap: 6,
              paddingHorizontal: spacing.xs,
              paddingVertical: 2,
              borderRadius: 4,
              backgroundColor: hovered && sortable ? colors.surfaceElevated : "transparent",
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
              <Text
                variant="caption"
                tone="accent"
                style={{ fontSize: 9, lineHeight: 12 }}
              >
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

export default function WatchlistDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [addSymbol, setAddSymbol] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [showStrategyAlerts, setShowStrategyAlerts] = useState(false);
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === "web" && width >= layout.wideBreakpoint;

  const { data: watchlists, isLoading, isFetching } = useQuery({
    queryKey: ["watchlists"],
    queryFn: watchlistsApi.list,
    refetchInterval: 60_000,
  });
  const watchlist = watchlists?.find((w) => w.id === id);

  const symbols = watchlist?.items.map((i) => i.symbol) ?? [];
  const symbolsKey = symbols.join(",");
  const strategy = watchlist?.strategy ?? "orb_vwap";

  const [entryMode, setEntryMode] = useState<"close" | "touch">("close");

  useEffect(() => {
    AsyncStorage.getItem(ENTRY_MODE_STORAGE_KEY).then((stored) => {
      if (stored === "close" || stored === "touch") {
        setEntryMode(stored);
      }
    });
  }, []);

  const handleEntryModeChange = (mode: "close" | "touch") => {
    setEntryMode(mode);
    AsyncStorage.setItem(ENTRY_MODE_STORAGE_KEY, mode).catch(() => {});
  };

  const { data: strategyNotifs } = useQuery({
    queryKey: ["strategy-notifications"],
    queryFn: settingsApi.getStrategyNotifications,
  });
  const activeAlertsCount = strategyNotifs?.strategies.filter((s) => s.enabled).length ?? 0;
  const { data: intradayData } = useQuery({
    queryKey: ["intraday", symbolsKey, strategy, entryMode],
    queryFn: () => stocksApi.intradaySnapshots(symbols, strategy, entryMode),
    enabled: symbols.length > 0,
    refetchInterval: 60_000,
    retry: false,
  });
  const intradayMap = intradayData?.snapshots ?? {};

  const { data: searchResults } = useQuery({
    queryKey: ["stock-search", addSymbol],
    queryFn: () => stocksApi.search(addSymbol),
    enabled: addSymbol.trim().length > 0,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["watchlists"] });

  const addMutation = useMutation({
    mutationFn: (symbol: string) => watchlistsApi.addItem(id, symbol),
    onSuccess: () => {
      setAddSymbol("");
      invalidate();
    },
  });

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => watchlistsApi.removeItem(id, symbol),
    onSuccess: invalidate,
  });

  const strategyMutation = useMutation({
    mutationFn: (next: string) => watchlistsApi.setStrategy(id, next),
    onSuccess: invalidate,
  });

  const resetTriggersMutation = useMutation({
    mutationFn: () =>
      stocksApi.clearFrozenTriggers(
        strategy,
        symbols.length > 0 ? symbols : undefined,
      ),
    onSuccess: () => {
      // Re-fetch intraday data immediately after clearing
      queryClient.invalidateQueries({ queryKey: ["intraday"] });
    },
  });

  const [sort, setSort] = useState<SortState>({ key: "support", dir: "asc" });

  if (isLoading || !watchlist) {
    return (
      <Screen>
        <LoadingBlock label="Loading watchlist…" />
      </Screen>
    );
  }

  return (
    <Screen width="wide">
      {/* Header */}
      <View
        style={{
          flexDirection: isDesktop ? "row" : "column",
          justifyContent: "space-between",
          alignItems: isDesktop ? "flex-end" : "flex-start",
          gap: spacing.md,
        }}
      >
        <View style={{ gap: spacing.xs, flex: 1 }}>
          <Pressable onPress={() => router.push("/(tabs)/watchlists")}>
            <Text variant="caption" tone="accent">
              ← All watchlists
            </Text>
          </Pressable>
          <Text variant="display">{watchlist.name}</Text>
          <Text variant="body" tone="secondary">
            {watchlist.items.length} stock{watchlist.items.length === 1 ? "" : "s"} · sorted by{" "}
            {COLUMN_HEADERS.find((c) => c.key === sort.key)?.label} ({sort.dir === "asc" ? "asc" : "desc"})
          </Text>
          <Text variant="caption" tone="muted">
            Prices auto-refresh every 60s
            {isFetching && !isLoading ? " · refreshing…" : ""}
          </Text>
          <StrategySelector
            value={strategy}
            onChange={(next) => strategyMutation.mutate(next)}
            loading={strategyMutation.isPending}
          />
          {strategy === "orb_pullback_support" && (
            <EntryModeToggle
              value={entryMode}
              onChange={handleEntryModeChange}
            />
          )}
        </View>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Button
            label={`🔔 Alerts (${activeAlertsCount})`}
            size="sm"
            variant="secondary"
            onPress={() => setShowStrategyAlerts(true)}
          />
          <Button
            label={isFetching ? "Refreshing…" : "Refresh"}
            size="sm"
            variant="secondary"
            loading={isFetching && !isLoading}
            onPress={invalidate}
          />
          <Button
            label={showAdd ? "Close" : "+ Add stock"}
            size="sm"
            onPress={() => setShowAdd((v) => !v)}
          />
          {strategy !== "orb_vwap" && (
            <Button
              label={resetTriggersMutation.isPending ? "Resetting…" : "🔄 Reset Triggers"}
              size="sm"
              variant="secondary"
              loading={resetTriggersMutation.isPending}
              onPress={() => resetTriggersMutation.mutate()}
            />
          )}
        </View>
      </View>

      {/* Add stock (collapsible) */}
      {showAdd ? (
        <Card style={{ gap: spacing.md }}>
          <Text variant="subtitle">Add a stock</Text>
          <Input
            placeholder="Search by symbol or company name"
            value={addSymbol}
            onChangeText={setAddSymbol}
            autoCapitalize="characters"
            autoFocus
          />
          <View style={{ gap: spacing.xs }}>
            {(searchResults ?? []).slice(0, 6).map((s) => {
              const alreadyAdded = watchlist.items.some((i) => i.symbol === s.symbol);
              return (
                <View
                  key={s.symbol}
                  style={{
                    flexDirection: "row",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingVertical: spacing.sm,
                    borderBottomWidth: 1,
                    borderBottomColor: colors.divider,
                  }}
                >
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text variant="bodyStrong">{s.symbol}</Text>
                    <Text variant="caption" tone="secondary" numberOfLines={1}>
                      {s.name}
                    </Text>
                  </View>
                  <Button
                    label={alreadyAdded ? "Added" : "+ Add"}
                    size="sm"
                    variant={alreadyAdded ? "ghost" : "secondary"}
                    disabled={alreadyAdded}
                    onPress={() => addMutation.mutate(s.symbol)}
                    loading={addMutation.isPending && addMutation.variables === s.symbol}
                  />
                </View>
              );
            })}
            {addSymbol.trim().length > 0 && (searchResults?.length ?? 0) === 0 ? (
              <Text variant="caption" tone="muted">
                No matches found.
              </Text>
            ) : null}
          </View>
        </Card>
      ) : null}

      {/* Holdings list */}
      {watchlist.items.length === 0 ? (
        <Card
          style={{
            alignItems: "center",
            gap: spacing.md,
            paddingVertical: spacing.xxxl,
            borderStyle: "dashed",
          }}
        >
          <Text variant="subtitle">This watchlist is empty</Text>
          <Text variant="caption" tone="secondary" style={{ textAlign: "center" }}>
            Add stocks to start tracking price and proximity to support.
          </Text>
          <Button label="+ Add your first stock" size="sm" onPress={() => setShowAdd(true)} />
        </Card>
      ) : (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ minWidth: 1140, width: "100%" }}
        >
          <View style={{ width: "100%", gap: spacing.xs }}>
            <IntradayLegend visible={Object.values(intradayMap).some((s) => s != null)} />
            <SortableHeader state={sort} onChange={setSort} />
            {sortItems(watchlist.items, sort).map((item) => (
              <StockRow
                key={item.symbol}
                item={item}
                intraday={intradayMap[item.symbol] ?? null}
                onPress={() => {
                  const href = openStock(item.symbol);
                  if (href) router.push(href);
                }}
                onRemove={() => removeMutation.mutate(item.symbol)}
              />
            ))}
          </View>
        </ScrollView>
      )}

      <StrategyAlertsModal
        visible={showStrategyAlerts}
        onClose={() => setShowStrategyAlerts(false)}
      />
    </Screen>
  );
}
