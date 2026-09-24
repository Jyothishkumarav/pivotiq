import React, { useEffect, useMemo, useState } from "react";
import { Animated, Platform, Pressable, ScrollView, useWindowDimensions, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, LoadingBlock, Screen, Text } from "@/components/ui";
import { StockRow } from "@/components/StockRow";
import { IndexRow } from "@/components/IndexRow";
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
  { key: "symbol", label: "Stop Loss", flex: 1.35, align: "flex-end", sortable: false },
  { key: "symbol", label: "Status", flex: 0.75, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ Entry", flex: 0.7, align: "flex-end", sortable: false },
  { key: "symbol", label: "Δ SL", flex: 0.7, align: "flex-end", sortable: false },
  { key: "symbol", label: "Max Run", flex: 0.75, align: "flex-end", sortable: false },
  { key: "symbol", label: "Time", flex: 0.65, align: "flex-end", sortable: false },
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
    let diff = 0;
    if (typeof va === "string" && typeof vb === "string") {
      diff = sign * va.localeCompare(vb);
    } else {
      diff = sign * (Number(va) - Number(vb));
    }
    if (diff !== 0) return diff;
    return a.symbol.localeCompare(b.symbol);
  });
}

const INTRADAY_LEGEND: { glyph: string; color: string; label: string }[] = [
  { glyph: "▲", color: "#3DDB9F", label: "Above ORB (bullish)" },
  { glyph: "◆", color: "#9AA9C7", label: "Inside ORB (range)" },
  { glyph: "▼", color: "#FF6B85", label: "Below ORB (bearish)" },
];

const STRATEGY_OPTIONS: { value: string; label: string; icon: string; shortLabel: string }[] = [
  { value: "orb_flow",            label: "ORB Institutional Flow", icon: "⚡", shortLabel: "Flow" },
  { value: "orb_pullback_support",label: "ORB + Pullback Support",icon: "🎯", shortLabel: "Support" },
  { value: "orb_pullback",        label: "ORB + VWAP Pullback",   icon: "🔄", shortLabel: "Pullback" },
];

const STRATEGY_COLORS: Record<string, { accent: string; glow: string; bg: string }> = {
  orb_flow:             { accent: "#7B61FF",        glow: "rgba(123,97,255,0.25)",  bg: "rgba(123,97,255,0.10)" },
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
const INCLUDE_FIRST_CANDLE_STORAGE_KEY = "pivotiq:include_first_candle";

function OrbPullbackControls({
  entryMode,
  onEntryModeChange,
  includeFirstCandle,
  onIncludeFirstCandleChange,
}: {
  entryMode: "close" | "touch";
  onEntryModeChange: (mode: "close" | "touch") => void;
  includeFirstCandle: boolean;
  onIncludeFirstCandleChange: (val: boolean) => void;
}) {
  return (
    <View style={{ gap: 4, marginTop: 6 }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.lg,
          flexWrap: "nowrap",
          ...(Platform.OS === "web" ? ({ overflowX: "auto" } as any) : {}),
        }}
      >
        {/* Trigger on Toggle */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexShrink: 0 }}>
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
              onPress={() => onEntryModeChange("close")}
              style={({ hovered }: any) => ({
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
                borderRadius: 6,
                backgroundColor:
                  entryMode === "close"
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
                  color: entryMode === "close" ? "#FFFFFF" : colors.textSecondary,
                  fontSize: 12,
                }}
              >
                🕯️ 3 Min Candle
              </Text>
            </Pressable>

            <Pressable
              onPress={() => onEntryModeChange("touch")}
              style={({ hovered }: any) => ({
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
                borderRadius: 6,
                backgroundColor:
                  entryMode === "touch"
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
                  color: entryMode === "touch" ? "#FFFFFF" : colors.textSecondary,
                  fontSize: 12,
                }}
              >
                ⚡ Latest Price
              </Text>
            </Pressable>
          </View>
        </View>

        {/* 9:15 Candle Toggle */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexShrink: 0 }}>
          <Text variant="caption" tone="secondary" style={{ fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
            9:15 Candle:
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
              onPress={() => onIncludeFirstCandleChange(false)}
              style={({ hovered }: any) => ({
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
                borderRadius: 6,
                backgroundColor:
                  !includeFirstCandle
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
                  color: !includeFirstCandle ? "#FFFFFF" : colors.textSecondary,
                  fontSize: 12,
                }}
              >
                🚫 Ignore (Matches ORB+VWAP)
              </Text>
            </Pressable>

            <Pressable
              onPress={() => onIncludeFirstCandleChange(true)}
              style={({ hovered }: any) => ({
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
                borderRadius: 6,
                backgroundColor:
                  includeFirstCandle
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
                  color: includeFirstCandle ? "#FFFFFF" : colors.textSecondary,
                  fontSize: 12,
                }}
              >
                ✅ Include First Candle
              </Text>
            </Pressable>
          </View>
        </View>
      </View>

      <Text variant="caption" tone="muted" style={{ fontSize: 11, lineHeight: 14 }}>
        {entryMode === "close"
          ? "3 Min Candle: Confirms entry only after 3m candle closes beyond supporting candle."
          : "Latest Price: Triggers entry immediately on live price / wick breach."}{" "}
        {!includeFirstCandle
          ? "9:15 auction spike ignored to determine heights (matches ORB + VWAP)."
          : "9:15 opening candle high/low included in ORB calculation."}
      </Text>
    </View>
  );
}

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
          // If it's today's date, it's represented by the Live button, but allow explicit selection if desired
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

  const [retestDate, setRetestDate] = useState<string | null>(null);
  const tradingDays = useMemo(() => getRecentTradingDays(30), []);

  const { data: watchlists, isLoading, isFetching } = useQuery({
    queryKey: ["watchlists"],
    queryFn: watchlistsApi.list,
    refetchInterval: 60_000,
  });
  const watchlist = watchlists?.find((w) => w.id === id);

  const symbols = watchlist?.items.map((i) => i.symbol) ?? [];
  const INDEX_SYMBOLS = useMemo(() => ["NIFTY50", "BANKNIFTY"], []);
  const allSymbols = useMemo(() => Array.from(new Set([...INDEX_SYMBOLS, ...symbols])), [symbols, INDEX_SYMBOLS]);
  const allSymbolsKey = allSymbols.join(",");
  const strategy = watchlist?.strategy ?? "orb_vwap";

  const [entryMode, setEntryMode] = useState<"close" | "touch">("close");
  const [includeFirstCandle, setIncludeFirstCandle] = useState<boolean>(false);

  useEffect(() => {
    AsyncStorage.getItem(ENTRY_MODE_STORAGE_KEY).then((stored) => {
      if (stored === "close" || stored === "touch") {
        setEntryMode(stored);
      }
    });
    AsyncStorage.getItem(INCLUDE_FIRST_CANDLE_STORAGE_KEY).then((stored) => {
      if (stored === "true" || stored === "false") {
        setIncludeFirstCandle(stored === "true");
      }
    });
  }, []);

  const handleEntryModeChange = (mode: "close" | "touch") => {
    setEntryMode(mode);
    AsyncStorage.setItem(ENTRY_MODE_STORAGE_KEY, mode).catch(() => {});
  };

  const handleIncludeFirstCandleChange = (val: boolean) => {
    setIncludeFirstCandle(val);
    AsyncStorage.setItem(INCLUDE_FIRST_CANDLE_STORAGE_KEY, String(val)).catch(() => {});
  };

  const { data: strategyNotifs } = useQuery({
    queryKey: ["strategy-notifications"],
    queryFn: settingsApi.getStrategyNotifications,
  });
  const HIDDEN_STRATEGIES = ["orb_vwap", "context_gated"];
  const activeAlertsCount =
    strategyNotifs?.strategies.filter((s) => !HIDDEN_STRATEGIES.includes(s.key) && s.enabled).length ?? 0;
  const { data: intradayData } = useQuery({
    queryKey: ["intraday", allSymbolsKey, strategy, entryMode, includeFirstCandle, retestDate],
    queryFn: () => stocksApi.intradaySnapshots(allSymbols, strategy, entryMode, retestDate, includeFirstCandle),
    enabled: allSymbols.length > 0,
    refetchInterval: retestDate ? false : 60_000,
    retry: false,
  });
  const intradayMap = intradayData?.snapshots ?? {};

  const { data: searchResults } = useQuery({
    queryKey: ["stock-search", addSymbol],
    queryFn: () => stocksApi.search(addSymbol),
    enabled: addSymbol.trim().length > 0,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    queryClient.invalidateQueries({ queryKey: ["intraday"] });
  };

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

  const [sort, setSort] = useState<SortState>({ key: "symbol", dir: "asc" });

  if (isLoading || !watchlist) {
    return (
      <Screen width="wide">
        <LoadingBlock label="Loading watchlist…" />
      </Screen>
    );
  }

  return (
    <Screen width="wide">
      {/* Header */}
      <View style={{ gap: spacing.md }}>
        <View
          style={{
            flexDirection: isDesktop ? "row" : "column",
            justifyContent: "space-between",
            alignItems: isDesktop ? "center" : "flex-start",
            gap: spacing.md,
          }}
        >
          <View style={{ gap: spacing.xs }}>
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
              {retestDate
                ? "Historical session · Retest mode (Read-only)"
                : `Prices auto-refresh every 60s${isFetching && !isLoading ? " · refreshing…" : ""}`}
            </Text>
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
            {strategy !== "orb_vwap" && !retestDate && (
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

        <View style={{ gap: spacing.xs, width: "100%" }}>
          <StrategySelector
            value={strategy}
            onChange={(next) => strategyMutation.mutate(next)}
            loading={strategyMutation.isPending}
          />
          {strategy === "orb_pullback_support" && (
            <OrbPullbackControls
              entryMode={entryMode}
              onEntryModeChange={handleEntryModeChange}
              includeFirstCandle={includeFirstCandle}
              onIncludeFirstCandleChange={handleIncludeFirstCandleChange}
            />
          )}
          {strategy === "orb_flow" && (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
                paddingHorizontal: spacing.md,
                paddingVertical: 7,
                borderRadius: 8,
                backgroundColor: "rgba(123,97,255,0.08)",
                borderWidth: 1,
                borderColor: "rgba(123,97,255,0.22)",
                marginTop: 4,
              }}
            >
              <Text style={{ fontSize: 13 }}>⚡</Text>
              <Text variant="caption" style={{ color: "#B8A7FF", fontWeight: "700" }}>
                Institutional Flow:
              </Text>
              <Text variant="caption" tone="secondary">
                3m Close Confirmation · Morning Window (≤ 10:30 IST) · Dynamic Confluence Sizing (1.0R / 0.5R)
              </Text>
            </View>
          )}
          <DateSelector
            value={retestDate}
            onChange={setRetestDate}
            days={tradingDays}
          />
        </View>
      </View>

      {/* Retest Banner */}
      {retestDate ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
            borderRadius: 8,
            backgroundColor: "rgba(245, 181, 74, 0.12)",
            borderWidth: 1,
            borderColor: "rgba(245, 181, 74, 0.35)",
            marginTop: spacing.xs,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Text style={{ fontSize: 14 }}>📅</Text>
            <Text variant="caption" style={{ color: "#F5B54A", fontWeight: "600" }}>
              Retest Mode · Viewing {tradingDays.find((d) => d.iso === retestDate)?.label ?? retestDate} (Read-Only)
            </Text>
          </View>
          <Pressable
            onPress={() => setRetestDate(null)}
            style={({ hovered }: any) => ({
              paddingHorizontal: spacing.sm,
              paddingVertical: 4,
              borderRadius: 4,
              backgroundColor: hovered ? "rgba(245, 181, 74, 0.25)" : "rgba(245, 181, 74, 0.18)",
            })}
          >
            <Text variant="caption" style={{ color: "#F5B54A", fontWeight: "700" }}>
              ✕ Return to Live
            </Text>
          </Pressable>
        </View>
      ) : null}

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
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ minWidth: 1140, width: "100%" }}
      >
        <View style={{ width: "100%", gap: spacing.xs }}>
          <IntradayLegend visible={Object.values(intradayMap).some((s) => s != null)} />
          <SortableHeader state={sort} onChange={setSort} />

          {/* Benchmark Market Indices */}
          <View style={{ gap: 4, marginBottom: spacing.xs }}>
            <IndexRow
              name="NIFTY 50"
              symbol="NIFTY50"
              intraday={intradayMap["NIFTY50"] ?? null}
              accentColor="#5B8BFF"
              onPress={() => {
                const href = openStock("NIFTY50");
                if (href) router.push(href);
              }}
            />
            <IndexRow
              name="BANK NIFTY"
              symbol="BANKNIFTY"
              intraday={intradayMap["BANKNIFTY"] ?? null}
              accentColor="#F5B54A"
              onPress={() => {
                const href = openStock("BANKNIFTY");
                if (href) router.push(href);
              }}
            />
          </View>

          {watchlist.items.length === 0 ? (
            <Card
              style={{
                alignItems: "center",
                gap: spacing.md,
                paddingVertical: spacing.xxxl,
                borderStyle: "dashed",
                marginTop: spacing.md,
              }}
            >
              <Text variant="subtitle">This watchlist is empty</Text>
              <Text variant="caption" tone="secondary" style={{ textAlign: "center" }}>
                Add stocks to start tracking price and proximity to support.
              </Text>
              <Button label="+ Add your first stock" size="sm" onPress={() => setShowAdd(true)} />
            </Card>
          ) : (
            <>
              {/* Subtle section label */}
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.sm, marginTop: spacing.xs, marginBottom: 2 }}>
                <Text variant="caption" tone="muted" style={{ textTransform: "uppercase", letterSpacing: 1, fontWeight: "600", fontSize: 11 }}>
                  Watchlist Stocks ({watchlist.items.length})
                </Text>
                <View style={{ flex: 1, height: 1, backgroundColor: colors.borderSubtle }} />
              </View>

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
            </>
          )}
        </View>
      </ScrollView>

      <StrategyAlertsModal
        visible={showStrategyAlerts}
        onClose={() => setShowStrategyAlerts(false)}
      />
    </Screen>
  );
}
