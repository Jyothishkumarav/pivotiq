import React, { useState } from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, LoadingBlock, Screen, Text } from "@/components/ui";
import { StockRow } from "@/components/StockRow";
import { watchlistsApi } from "@/api/watchlists";
import { stocksApi } from "@/api/stocks";
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
  { key: "symbol", label: "Symbol", flex: 2.0, align: "flex-start", sortable: true },
  { key: "ltp", label: "LTP", flex: 0.85, align: "flex-end", sortable: true },
  { key: "dayChange", label: "Day", flex: 0.75, align: "flex-end", sortable: true },
  { key: "symbol", label: "Setup", flex: 0.75, align: "flex-end", sortable: false },
  { key: "symbol", label: "Entry / SL", flex: 1.2, align: "flex-end", sortable: false },
  { key: "symbol", label: "Status", flex: 0.85, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ Entry", flex: 0.75, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ SL", flex: 0.75, align: "flex-end", sortable: false },
  { key: "symbol", label: "Time", flex: 0.85, align: "flex-end", sortable: false },
  { key: "support", label: "Support", flex: 1.05, align: "flex-end", sortable: true },
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
  const { data: intradayData } = useQuery({
    queryKey: ["intraday", symbolsKey],
    queryFn: () => stocksApi.intradaySnapshots(symbols),
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
        </View>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
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
        <View style={{ gap: spacing.xs }}>
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
      )}
    </Screen>
  );
}
