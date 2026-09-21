import React, { useState } from "react";
import { Linking, Platform, Pressable, useWindowDimensions, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Screen, Text } from "@/components/ui";
import { SupportLevelCard } from "@/components/SupportLevelCard";
import { StockDetailsSections } from "@/components/StockDetailsSections";
import { CandleChart, buildOverlays, OVERLAY_METHOD_LABELS, OverlayMethod, Overlay } from "@/components/CandleChart";
import { TradePanel } from "@/components/TradePanel";
import { fyersApi } from "@/api/fyers";
import { stocksApi } from "@/api/stocks";
import { watchlistsApi } from "@/api/watchlists";
import { colors, layout, spacing } from "@/theme/tokens";
import { formatCompactCurrency, formatCurrency, formatIstTime, formatPercent, formatRelativeTime } from "@/utils/format";
import { IntradaySnapshot, TradeSetup } from "@/types";

function TradingViewLink({ symbol }: { symbol: string }) {
  const url = `https://in.tradingview.com/chart/?symbol=NSE%3A${encodeURIComponent(symbol.toUpperCase())}`;
  const open = () => {
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    } else {
      Linking.openURL(url).catch(() => undefined);
    }
  };
  return (
    <Pressable
      onPress={open}
      hitSlop={6}
      style={({ hovered }: any) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: spacing.sm,
        paddingVertical: 2,
        borderRadius: 999,
        borderWidth: 1,
        borderColor: hovered ? colors.accent : colors.borderSubtle,
        backgroundColor: hovered ? colors.accentMuted : "transparent",
      })}
    >
      <Text variant="caption" style={{ color: colors.accent, fontSize: 11 }}>
        📈 Chart on TradingView ↗
      </Text>
    </Pressable>
  );
}

const INTRADAY_TREND_META = {
  up: { color: "#3DDB9F", label: "Uptrend", desc: "Price broke above the opening range — long bias." },
  down: { color: "#FF6B85", label: "Downtrend", desc: "Price broke below the opening range — short bias." },
  flat: { color: "#9AA9C7", label: "Range-bound", desc: "Price still inside the opening range." },
} as const;

function IntradayPanel({
  snapshot,
  fyersConnected,
}: {
  snapshot: IntradaySnapshot | null;
  fyersConnected?: boolean;
}) {
  if (!snapshot) {
    return (
      <Card style={{ gap: spacing.xs }}>
        <Text variant="subtitle">Intraday trend</Text>
        <Text variant="caption" tone="muted">
          {fyersConnected
            ? "Market closed (09:15–15:30 IST) · No intraday session data available for today yet."
            : "Connect Fyers to see the first-15-min opening range, VWAP, and today's trend bias."}
        </Text>
      </Card>
    );
  }
  const meta = INTRADAY_TREND_META[snapshot.trend];
  return (
    <Card style={{ gap: spacing.md }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ gap: 2 }}>
          <Text variant="subtitle">Intraday trend</Text>
          <Text variant="caption" tone="muted">
            First 20 min · {snapshot.candleCount} × 5-min candles ·{" "}
            {snapshot.swingComplete ? "Range confirmed" : "Range forming…"} · Updated{" "}
            {formatRelativeTime(snapshot.updatedAt)}
          </Text>
        </View>
        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingVertical: 4,
            borderRadius: 999,
            backgroundColor: `${meta.color}22`,
            borderWidth: 1,
            borderColor: `${meta.color}66`,
          }}
        >
          <Text style={{ color: meta.color, fontWeight: "600", fontSize: 12 }}>
            {snapshot.trend === "up" ? "▲" : snapshot.trend === "down" ? "▼" : "◆"} {meta.label}
          </Text>
        </View>
      </View>
      <Text variant="caption" tone="secondary">
        {meta.desc}
      </Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.lg }}>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Swing high (resistance)
          </Text>
          <Text variant="mono" tone="negative">
            {formatCurrency(snapshot.openingRangeHigh)}
          </Text>
          {snapshot.swingHighAt ? (
            <Text variant="caption" tone="muted">
              formed {formatIstTime(snapshot.swingHighAt)} IST
            </Text>
          ) : null}
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Swing low (support)
          </Text>
          <Text variant="mono" tone="positive">
            {formatCurrency(snapshot.openingRangeLow)}
          </Text>
          {snapshot.swingLowAt ? (
            <Text variant="caption" tone="muted">
              formed {formatIstTime(snapshot.swingLowAt)} IST
            </Text>
          ) : null}
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            VWAP
          </Text>
          <Text variant="mono">{formatCurrency(snapshot.vwap)}</Text>
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Day range
          </Text>
          <Text variant="mono">
            {formatCurrency(snapshot.dayLow)} – {formatCurrency(snapshot.dayHigh)}
          </Text>
        </View>
      </View>
    </Card>
  );
}

const SETUP_META = {
  buy: { color: "#3DDB9F", label: "BUY", icon: "▲" },
  sell: { color: "#FF6B85", label: "SELL", icon: "▼" },
} as const;

function TradeSetupCard({ setup, currentPrice }: { setup: TradeSetup; currentPrice: number }) {
  const meta = SETUP_META[setup.action];
  const rr = setup.riskRewardRatio;
  const rawDiff = currentPrice - setup.entry;
  // For a SELL, price below entry = profit. Flip sign so positive = favorable in both directions.
  const signedDiff = setup.action === "sell" ? -rawDiff : rawDiff;
  const pctFromEntry = setup.entry > 0 ? (signedDiff / setup.entry) * 100 : 0;
  const triggered = signedDiff > 0;
  const atEntry = Math.abs(pctFromEntry) < 0.05;
  const distanceTone: "positive" | "negative" | "warning" | "muted" = atEntry
    ? "warning"
    : triggered
      ? "positive"
      : "muted";
  const distanceLabel = atEntry
    ? "At entry"
    : triggered
      ? "Already triggered"
      : "Waiting for entry";
  return (
    <Card style={{ gap: spacing.md, borderColor: `${meta.color}55`, borderWidth: 1 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ gap: 2 }}>
          <Text variant="subtitle">Trade setup</Text>
          <Text variant="caption" tone="muted">
            Auto-generated from ORB + VWAP — not financial advice
          </Text>
        </View>
        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingVertical: 6,
            borderRadius: 999,
            backgroundColor: `${meta.color}22`,
            borderWidth: 1,
            borderColor: `${meta.color}66`,
          }}
        >
          <Text style={{ color: meta.color, fontWeight: "700", fontSize: 13, letterSpacing: 1 }}>
            {meta.icon} {meta.label}
          </Text>
        </View>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.lg }}>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Current price
          </Text>
          <Text variant="mono" style={{ fontSize: 16 }}>
            {formatCurrency(currentPrice)}
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Entry near
          </Text>
          <Text variant="mono" style={{ fontSize: 16 }}>
            {formatCurrency(setup.entry)}
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 130 }}>
          <Text variant="caption" tone="muted">
            {distanceLabel}
          </Text>
          <Text variant="mono" tone={distanceTone} style={{ fontSize: 16 }}>
            {signedDiff >= 0 ? "+" : "−"}
            {formatCurrency(Math.abs(rawDiff))} ({formatPercent(pctFromEntry)})
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            {setup.slWide && Math.abs(setup.slWide - setup.stopLoss) > 0.05 ? "Tight Stop" : "Stop loss"}
          </Text>
          <Text variant="mono" tone="negative" style={{ fontSize: 16 }}>
            {formatCurrency(setup.stopLoss)}
          </Text>
        </View>
        {setup.slWide && Math.abs(setup.slWide - setup.stopLoss) > 0.05 && (
          <View style={{ flex: 1, minWidth: 110 }}>
            <Text variant="caption" tone="muted">
              Macro Stop (MSL)
            </Text>
            <Text variant="mono" tone="negative" style={{ fontSize: 16 }}>
              {formatCurrency(setup.slWide)}
            </Text>
          </View>
        )}
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Target (1R)
          </Text>
          <Text variant="mono" tone="positive" style={{ fontSize: 16 }}>
            {formatCurrency(setup.target)}
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 110 }}>
          <Text variant="caption" tone="muted">
            Risk : Reward
          </Text>
          <Text variant="mono" style={{ fontSize: 16 }}>
            {rr > 0 ? `1 : ${rr}` : "—"}
          </Text>
        </View>
      </View>
      <Text variant="caption" tone="secondary">
        {setup.rationale}
      </Text>
    </Card>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <View
      style={{
        flexDirection: "row",
        justifyContent: "space-between",
        paddingVertical: spacing.sm,
        borderBottomWidth: 1,
        borderBottomColor: colors.divider,
      }}
    >
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Text variant="mono">{value}</Text>
    </View>
  );
}

function ProximityMessage({ ltp, overlays }: { ltp: number; overlays: Overlay[] }) {
  const supports = overlays.filter((o) => o.tone === "support" || o.tone === "pivot").filter((o) => o.value <= ltp);
  const resistances = overlays.filter((o) => o.tone === "resistance" || o.tone === "pivot").filter((o) => o.value >= ltp);

  const nearestSupport = supports.length ? supports.reduce((a, b) => (a.value > b.value ? a : b)) : null;
  const nearestResistance = resistances.length ? resistances.reduce((a, b) => (a.value < b.value ? a : b)) : null;

  return (
    <View
      style={{
        backgroundColor: colors.background,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: colors.borderSubtle,
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: spacing.sm }}>
        <Text variant="caption" tone="secondary" style={{ textTransform: "uppercase", letterSpacing: 1 }}>
          Current price
        </Text>
        <Text variant="subtitle">{formatCurrency(ltp)}</Text>
      </View>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.lg }}>
        {nearestSupport ? (
          <View style={{ flex: 1, minWidth: 220, gap: spacing.xs }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              <View style={{ width: 6, height: 6, borderRadius: 999, backgroundColor: colors.positive }} />
              <Text variant="caption" tone="muted">
                Nearest support · {nearestSupport.label}
              </Text>
            </View>
            <Text variant="bodyStrong">
              {formatCurrency(nearestSupport.value)}{" "}
              <Text variant="body" tone="positive">
                ({formatPercent(((ltp - nearestSupport.value) / ltp) * 100)} above)
              </Text>
            </Text>
          </View>
        ) : (
          <View style={{ flex: 1, minWidth: 220 }}>
            <Text variant="caption" tone="muted">
              Price is below all selected supports.
            </Text>
          </View>
        )}

        {nearestResistance ? (
          <View style={{ flex: 1, minWidth: 220, gap: spacing.xs }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              <View style={{ width: 6, height: 6, borderRadius: 999, backgroundColor: colors.negative }} />
              <Text variant="caption" tone="muted">
                Nearest resistance · {nearestResistance.label}
              </Text>
            </View>
            <Text variant="bodyStrong">
              {formatCurrency(nearestResistance.value)}{" "}
              <Text variant="body" tone="negative">
                ({formatPercent(((nearestResistance.value - ltp) / ltp) * 100)} away)
              </Text>
            </Text>
          </View>
        ) : (
          <View style={{ flex: 1, minWidth: 220 }}>
            <Text variant="caption" tone="muted">
              Price is above all selected resistances.
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}

export default function StockDetailScreen() {
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [chartMethod, setChartMethod] = useState<OverlayMethod>("classic");
  const [overlayFilter, setOverlayFilter] = useState<"all" | "support" | "resistance">("all");

  const { width } = useWindowDimensions();
  const twoColumn = Platform.OS === "web" && width >= layout.wideBreakpoint;

  const { data: quote, isFetching: quoteFetching } = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => stocksApi.quote(symbol),
    refetchInterval: 30_000,
  });
  const { data: fundamentals, isLoading: fundamentalsLoading, isFetching: fundamentalsFetching } = useQuery({
    queryKey: ["fundamentals", symbol],
    queryFn: () => stocksApi.fundamentals(symbol),
  });
  const { data: details, isLoading: detailsLoading, isFetching: detailsFetching } = useQuery({
    queryKey: ["details", symbol],
    queryFn: () => stocksApi.details(symbol),
    retry: false,
  });
  const refreshDetailsMutation = useMutation({
    mutationFn: () => stocksApi.details(symbol, true),
    onSuccess: (fresh) => {
      queryClient.setQueryData(["details", symbol], fresh);
    },
  });
  const { data: levels, isLoading: levelsLoading, isFetching: levelsFetching } = useQuery({
    queryKey: ["support-levels", symbol],
    queryFn: () => stocksApi.supportLevels(symbol),
  });
  const { data: candlesData, isLoading: candlesLoading, isFetching: candlesFetching } = useQuery({
    queryKey: ["candles", symbol, "1y", "1d"],
    queryFn: () => stocksApi.candles(symbol, "1y", "1d"),
    staleTime: 4 * 60 * 60 * 1000,
  });
  const { data: intraday } = useQuery({
    queryKey: ["intraday", symbol],
    queryFn: () => stocksApi.intradaySnapshot(symbol),
    refetchInterval: 60_000,
    retry: false,
  });
  const { data: fyersStatus } = useQuery({
    queryKey: ["fyers", "status"],
    queryFn: fyersApi.status,
    refetchInterval: 60_000,
  });
  const isFyersConnected = fyersStatus?.connected ?? false;
  const { data: watchlists } = useQuery({ queryKey: ["watchlists"], queryFn: watchlistsApi.list });

  const addToWatchlistMutation = useMutation({
    mutationFn: (watchlistId: string) => watchlistsApi.addItem(watchlistId, symbol),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watchlists"] }),
  });

  if (!quote) {
    return (
      <Screen>
        <LoadingBlock label={`Fetching ${symbol}…`} />
      </Screen>
    );
  }

  const isUp = quote.changePercent >= 0;

  const allOverlays = buildOverlays(levels, chartMethod);
  const filteredOverlays =
    overlayFilter === "all"
      ? allOverlays
      : allOverlays.filter(
          (o) =>
            (overlayFilter === "support" && (o.tone === "support" || o.tone === "pivot")) ||
            (overlayFilter === "resistance" && (o.tone === "resistance" || o.tone === "pivot")),
        );

  const leftColumn = (
    <View style={{ gap: spacing.lg, flex: 1 }}>
      <Card elevated style={{ gap: spacing.md }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
          <View style={{ gap: spacing.xs, flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <Text variant="caption" tone="secondary" style={{ textTransform: "uppercase", letterSpacing: 1.5 }}>
                {quote.exchange}
              </Text>
              <TradingViewLink symbol={quote.symbol} />
            </View>
            <Text variant="display">{quote.symbol}</Text>
            <Text variant="body" tone="secondary" numberOfLines={1}>
              {quote.name}
            </Text>
          </View>
          <Badge label={isUp ? "Up" : "Down"} tone={isUp ? "positive" : "negative"} />
        </View>
        <View
          style={{
            flexDirection: "row",
            alignItems: "baseline",
            gap: spacing.md,
            paddingTop: spacing.sm,
            borderTopWidth: 1,
            borderTopColor: colors.divider,
          }}
        >
          <Text variant="display" style={{ fontSize: 34 }}>
            {formatCurrency(quote.ltp)}
          </Text>
          <Text variant="bodyStrong" tone={isUp ? "positive" : "negative"}>
            {isUp ? "▲" : "▼"} {formatCurrency(Math.abs(quote.change))} ({formatPercent(quote.changePercent)})
          </Text>
        </View>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.lg }}>
          <View style={{ flex: 1, minWidth: 90 }}>
            <Text variant="caption" tone="muted">Open</Text>
            <Text variant="mono">{formatCurrency(quote.open)}</Text>
          </View>
          <View style={{ flex: 1, minWidth: 90 }}>
            <Text variant="caption" tone="muted">High</Text>
            <Text variant="mono">{formatCurrency(quote.high)}</Text>
          </View>
          <View style={{ flex: 1, minWidth: 90 }}>
            <Text variant="caption" tone="muted">Low</Text>
            <Text variant="mono">{formatCurrency(quote.low)}</Text>
          </View>
          <View style={{ flex: 1, minWidth: 90 }}>
            <Text variant="caption" tone="muted">Prev close</Text>
            <Text variant="mono">{formatCurrency(quote.prevClose)}</Text>
          </View>
        </View>
        <Text variant="caption" tone="muted">
          {quoteFetching ? "Refreshing…" : `Updated ${formatRelativeTime(quote.lastUpdated)} · refreshes every 30s`}
        </Text>
      </Card>

      <IntradayPanel snapshot={intraday ?? null} fyersConnected={isFyersConnected} />

      {intraday?.tradeSetup ? (
        <TradeSetupCard setup={intraday.tradeSetup} currentPrice={quote.ltp} />
      ) : null}

      {detailsLoading ? (
        <Card>
          <LoadingBlock label="Fetching stock details…" compact />
        </Card>
      ) : details ? (
        <View style={{ gap: spacing.sm }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text variant="title">Details</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
              {refreshDetailsMutation.isPending || detailsFetching ? (
                <Text variant="caption" tone="muted">
                  Refreshing…
                </Text>
              ) : null}
              <Button
                label="Refresh from Yahoo"
                size="sm"
                variant="secondary"
                loading={refreshDetailsMutation.isPending}
                onPress={() => refreshDetailsMutation.mutate()}
              />
            </View>
          </View>
          <StockDetailsSections details={details} />
        </View>
      ) : fundamentalsLoading ? (
        <Card>
          <LoadingBlock label="Fetching fundamentals…" compact />
        </Card>
      ) : fundamentals ? (
        <Card style={{ gap: spacing.xs }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm }}>
            <Text variant="subtitle">Fundamentals</Text>
            {fundamentalsFetching ? (
              <Text variant="caption" tone="muted">
                Refreshing…
              </Text>
            ) : null}
          </View>
          <StatRow label="Market cap" value={formatCompactCurrency(fundamentals.marketCap)} />
          <StatRow label="P/E ratio" value={fundamentals.peRatio.toFixed(1)} />
          <StatRow label="P/B ratio" value={fundamentals.pbRatio.toFixed(1)} />
          <StatRow label="EPS" value={formatCurrency(fundamentals.eps)} />
          <StatRow label="52-week high" value={formatCurrency(fundamentals.week52High)} />
          <StatRow label="52-week low" value={formatCurrency(fundamentals.week52Low)} />
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: spacing.sm }}>
            <Text variant="caption" tone="secondary">
              Dividend yield
            </Text>
            <Text variant="mono">{fundamentals.dividendYield.toFixed(2)}%</Text>
          </View>
        </Card>
      ) : null}

      <Card style={{ gap: spacing.md }}>
        <Text variant="subtitle">Add to watchlist</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
          {(watchlists ?? []).map((wl) => (
            <Button
              key={wl.id}
              label={wl.name}
              size="sm"
              variant="secondary"
              onPress={() => addToWatchlistMutation.mutate(wl.id)}
            />
          ))}
        </View>
        {(watchlists?.length ?? 0) === 0 ? (
          <Text variant="caption" tone="muted">
            Create a watchlist from the Watchlists tab first.
          </Text>
        ) : null}
      </Card>

      <TradePanel symbol={quote.symbol} ltp={quote.ltp} dayChangePercent={quote.changePercent} />
    </View>
  );

  const rightColumn = (
    <View style={{ gap: spacing.lg, flex: 1 }}>
      <Card style={{ gap: spacing.md }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <View style={{ gap: spacing.xs }}>
            <Text variant="title">1-year price chart</Text>
            <Text variant="caption" tone="secondary">
              Daily candles · pick a method to overlay S/R levels
            </Text>
          </View>
          <Button
            label={candlesFetching ? "…" : "Refresh"}
            size="sm"
            variant="secondary"
            loading={candlesFetching}
            onPress={() => queryClient.invalidateQueries({ queryKey: ["candles", symbol, "1y", "1d"] })}
          />
        </View>

        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
          {(Object.keys(OVERLAY_METHOD_LABELS) as OverlayMethod[]).map((m) => {
            const active = chartMethod === m;
            const dot =
              m === "none"
                ? colors.textMuted
                : m === "swingLow"
                  ? colors.accent
                  : colors.positive;
            return (
              <Pressable
                key={m}
                onPress={() => setChartMethod(m)}
                style={({ hovered }: any) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.xs,
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.xs,
                  borderRadius: 999,
                  borderWidth: 1,
                  borderColor: active ? colors.accent : colors.borderSubtle,
                  backgroundColor: active
                    ? colors.accentMuted
                    : hovered
                      ? colors.surfaceElevated
                      : "transparent",
                })}
              >
                {m !== "none" ? (
                  <View style={{ width: 6, height: 6, borderRadius: 999, backgroundColor: dot }} />
                ) : null}
                <Text
                  variant="caption"
                  style={{
                    color: active ? colors.textPrimary : colors.textSecondary,
                    fontWeight: active ? "600" : "500",
                  }}
                >
                  {OVERLAY_METHOD_LABELS[m]}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {chartMethod !== "none" ? (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" }}>
            <Text variant="caption" tone="muted" style={{ marginRight: spacing.xs }}>
              Show:
            </Text>
            {(["all", "support", "resistance"] as const).map((f) => {
              const active = overlayFilter === f;
              const dot =
                f === "support" ? colors.positive : f === "resistance" ? colors.negative : colors.accent;
              const label = f === "all" ? "Both" : f === "support" ? "Support only" : "Resistance only";
              return (
                <Pressable
                  key={f}
                  onPress={() => setOverlayFilter(f)}
                  style={({ hovered }: any) => ({
                    flexDirection: "row",
                    alignItems: "center",
                    gap: spacing.xs,
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.xs,
                    borderRadius: 999,
                    borderWidth: 1,
                    borderColor: active ? dot : colors.borderSubtle,
                    backgroundColor: active
                      ? colors.surfaceElevated
                      : hovered
                        ? colors.surfaceElevated
                        : "transparent",
                  })}
                >
                  <View style={{ width: 6, height: 6, borderRadius: 999, backgroundColor: dot }} />
                  <Text
                    variant="caption"
                    style={{ color: active ? colors.textPrimary : colors.textSecondary }}
                  >
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}

        {candlesLoading ? (
          <LoadingBlock label="Loading 1-year daily candles…" />
        ) : (
          <CandleChart
            candles={candlesData?.candles ?? []}
            overlays={filteredOverlays}
          />
        )}

        {quote && chartMethod !== "none" && filteredOverlays.length > 0 ? (
          <ProximityMessage ltp={quote.ltp} overlays={filteredOverlays} />
        ) : null}
      </Card>

      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" }}>
        <View style={{ gap: spacing.xs, flex: 1 }}>
          <Text variant="title">Support &amp; resistance</Text>
          <Text variant="caption" tone="secondary">
            Computed from the prior session's high, low, and close.
          </Text>
          {levelsFetching && !levelsLoading ? (
            <Text variant="caption" tone="muted">
              Refreshing levels…
            </Text>
          ) : null}
        </View>
        <Button
          label={levelsFetching ? "…" : "Refresh"}
          size="sm"
          variant="secondary"
          loading={levelsFetching}
          onPress={() => queryClient.invalidateQueries({ queryKey: ["support-levels", symbol] })}
        />
      </View>

      {levelsLoading ? (
        <Card>
          <LoadingBlock label="Computing pivot & swing-low levels…" />
        </Card>
      ) : (levels?.pivotMethods ?? []).length === 0 ? (
        <Card>
          <Text variant="body" tone="muted">
            No level data available for this symbol.
          </Text>
        </Card>
      ) : (
        (levels?.pivotMethods ?? []).map((set) => (
          <View key={set.method} style={{ gap: spacing.xs }}>
            <SupportLevelCard set={set} />
            <Button
              label={`Set alert on ${set.method} S1`}
              size="sm"
              variant="ghost"
              onPress={() =>
                router.push({
                  pathname: "/alert/new",
                  params: { symbol, method: set.method, levelKey: "s1", levelValue: String(set.s1) },
                })
              }
            />
          </View>
        ))
      )}

      {levels?.swingLowZones.length ? (
        <Card style={{ gap: spacing.md }}>
          <Text variant="subtitle">Swing-low zones</Text>
          {levels.swingLowZones.map((z, idx) => (
            <View
              key={idx}
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
                paddingVertical: spacing.sm,
                borderBottomWidth: idx < levels.swingLowZones.length - 1 ? 1 : 0,
                borderBottomColor: colors.divider,
              }}
            >
              <View>
                <Text variant="body">{formatCurrency(z.level)}</Text>
                <Text variant="caption" tone="muted">
                  touched {z.touchCount}×
                </Text>
              </View>
              <Button
                label="Alert"
                size="sm"
                variant="ghost"
                onPress={() =>
                  router.push({
                    pathname: "/alert/new",
                    params: { symbol, method: "swingLow", levelKey: `zone-${idx}`, levelValue: String(z.level) },
                  })
                }
              />
            </View>
          ))}
        </Card>
      ) : null}
    </View>
  );

  return (
    <Screen width="wide">
      <View
        style={{
          flexDirection: twoColumn ? "row" : "column",
          gap: spacing.xl,
          alignItems: "flex-start",
        }}
      >
        {leftColumn}
        {rightColumn}
      </View>
    </Screen>
  );
}
