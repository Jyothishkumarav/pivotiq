import React, { useEffect, useState } from "react";
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from "react-native";

import { useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  Input,
  LoadingBlock,
  Screen,
  Text,
} from "@/components/ui";
import { settingsApi, TradingSettingsResponse, WatchlistOption } from "@/api/settings";
import { colors, layout, radius, spacing, typography } from "@/theme/tokens";
import { formatCurrency } from "@/utils/format";

const CAPITAL_PRESETS = [50_000, 100_000, 200_000, 500_000, 1_000_000];
const SL_BUFFER_PRESETS = [20, 25, 40, 50, 70, 75, 80, 100];
const RISK_PRESETS = [500, 800, 1000, 1100, 1500, 2000];
const POSITIONS_PRESETS = [5, 10, 15, 20];

export default function SettingsScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<TradingSettingsResponse>({
    queryKey: ["trading-settings"],
    queryFn: () => settingsApi.getTradingSettings(),
  });

  const [capital, setCapital] = useState<string>("100000");
  const [slBuffer, setSlBuffer] = useState<string>("25");
  const [maxRisk, setMaxRisk] = useState<string>("1100");
  const [maxPositions, setMaxPositions] = useState<string>("10");
  const [selectedWatchlist, setSelectedWatchlist] = useState<string>("all");
  const [entryMode, setEntryMode] = useState<"close" | "touch">("close");
  const [swingSlEnabled, setSwingSlEnabled] = useState<boolean>(false);
  const [swingSlBuffer, setSwingSlBuffer] = useState<string>("1");
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (data) {
      setCapital(String(data.paperCapital || 100_000));
      setSlBuffer(String(data.slBufferPct || 25));
      setMaxRisk(String(data.maxRiskPerTrade || 1100));
      setMaxPositions(String(data.maxOpenPositions || 10));
      setSelectedWatchlist(data.activeWatchlistId || "all");
      if (data.entryMode === "touch" || data.entryMode === "close") {
        setEntryMode(data.entryMode);
      }
      setSwingSlEnabled(Boolean(data.swingSlEnabled));
      setSwingSlBuffer(String(data.swingSlBufferPct ?? 1));
    }
  }, [data]);

  const updateMutation = useMutation({
    mutationFn: (payload: {
      paperCapital: number;
      slBufferPct: number;
      maxRiskPerTrade: number;
      maxOpenPositions: number;
      activeWatchlistId: string | null;
      entryMode: "close" | "touch";
    }) => settingsApi.updateTradingSettings(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(["trading-settings"], updated);
      queryClient.invalidateQueries({ queryKey: ["broker-funds"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-positions"] });
      queryClient.invalidateQueries({ queryKey: ["trading-positions"] });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  if (isLoading) {
    return (
      <Screen style={{ justifyContent: "center", alignItems: "center" }}>
        <LoadingBlock label="Loading trading settings…" />
      </Screen>
    );
  }

  const numCapital = Math.max(10_000, Number(capital) || 100_000);
  const numBuffer = Math.min(100, Math.max(1, Number(slBuffer) || 25));
  const numRisk = Math.max(100, Number(maxRisk) || 1100);
  const numPositions = Math.max(1, Number(maxPositions) || 10);
  const buyingPower = numCapital * 5.0;
  const maxMarginPerPosition = numCapital / numPositions;

  // Example Live Preview Calculation (e.g. KEI stock entry)
  const sampleEntry = 4653.5;
  const sampleTightSl = 4648.0;
  const sampleRawRisk = sampleEntry - sampleTightSl; // 5.50
  const sampleBufferAmt = sampleRawRisk * (numBuffer / 100.0);
  const sampleBufferedSl = Math.round((sampleTightSl - sampleBufferAmt) * 20) / 20;
  const sampleRiskPerShare = Math.max(0.05, sampleEntry - sampleBufferedSl);
  const sampleQtyByCapital = Math.floor((maxMarginPerPosition * 5.0) / sampleEntry);
  const sampleQtyByRisk = Math.floor(numRisk / sampleRiskPerShare);
  const sampleFinalQty = Math.max(0, Math.min(sampleQtyByCapital, sampleQtyByRisk));
  const sampleTotalRisk = Math.round(sampleFinalQty * sampleRiskPerShare * 100) / 100;
  const sampleMarginRequired = Math.round(((sampleFinalQty * sampleEntry) / 5.0) * 100) / 100;

  const handleSave = () => {
    updateMutation.mutate({
      paperCapital: numCapital,
      slBufferPct: numBuffer,
      maxRiskPerTrade: numRisk,
      maxOpenPositions: numPositions,
      activeWatchlistId: selectedWatchlist === "all" ? null : selectedWatchlist,
      entryMode,
      swingSlEnabled,
      swingSlBufferPct: Math.max(0, Number(swingSlBuffer) || 1),
    });
  };

  const handleReset = () => {
    setCapital("100000");
    setSlBuffer("25");
    setMaxRisk("1100");
    setMaxPositions("10");
    setSelectedWatchlist("all");
    setEntryMode("close");
    setSwingSlEnabled(false);
    setSwingSlBuffer("1");
  };

  const watchlists: WatchlistOption[] = data?.availableWatchlists || [];

  return (
    <Screen style={{ backgroundColor: colors.background }}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.container}>
          {/* Header navigation bar */}
          <View style={styles.headerRow}>
            <View style={{ gap: spacing.xs, flex: 1 }}>
              <Pressable
                onPress={() => router.back()}
                style={({ hovered }: any) => [
                  styles.backBtn,
                  hovered && { backgroundColor: colors.surfaceElevated },
                ]}
              >
                <Text variant="caption" tone="accent" style={{ fontWeight: "700" }}>
                  ← Back
                </Text>
              </Pressable>
              <Text variant="display" style={{ fontSize: 24, fontWeight: "800", letterSpacing: -0.5 }}>
                Trading & Execution Settings
              </Text>
              <Text variant="body" tone="secondary">
                Configure paper sandbox capital, tight stop-loss buffers, risk limits, and automated trading targets.
              </Text>
            </View>

            <View style={styles.actionsTop}>
              {saveSuccess ? (
                <Badge label="✓ Settings Saved" tone="positive" />
              ) : null}
              <Button
                label={updateMutation.isPending ? "Saving…" : "Save Changes"}
                onPress={handleSave}
                loading={updateMutation.isPending}
                size="md"
              />
            </View>
          </View>

          {/* 1. PAPER TRADING CAPITAL */}
          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Paper Trading Account Funds</Text>
                  <Badge label="5x Intraday MIS" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  Set starting capital for simulated paper trading. All buying power is multiplied by 5x leverage.
                </Text>
              </View>
            </View>

            <View style={styles.formRow}>
              <View style={{ flex: 1 }}>
                <Input
                  label="Available Sandbox Capital (₹)"
                  value={capital}
                  onChangeText={setCapital}
                  keyboardType="numeric"
                  placeholder="100000"
                  rightElement={
                    <Text variant="caption" tone="muted" style={{ paddingRight: spacing.sm }}>
                      INR
                    </Text>
                  }
                />
              </View>

              <View style={styles.statBox}>
                <Text variant="caption" tone="muted">5x Buying Power</Text>
                <Text variant="subtitle" tone="accent" style={{ fontWeight: "700" }}>
                  {formatCurrency(buyingPower)}
                </Text>
              </View>

              <View style={styles.statBox}>
                <Text variant="caption" tone="muted">Margin / Trade (10x split)</Text>
                <Text variant="subtitle" style={{ color: colors.textPrimary, fontWeight: "700" }}>
                  {formatCurrency(maxMarginPerPosition)}
                </Text>
              </View>
            </View>

            {/* Capital Preset Chips */}
            <View style={styles.presetsRow}>
              <Text variant="caption" tone="muted" style={{ marginRight: spacing.xs }}>
                Presets:
              </Text>
              {CAPITAL_PRESETS.map((p) => {
                const isSelected = numCapital === p;
                return (
                  <Pressable
                    key={p}
                    onPress={() => setCapital(String(p))}
                    style={({ hovered }: any) => [
                      styles.chip,
                      isSelected && styles.chipActive,
                      hovered && !isSelected && styles.chipHovered,
                    ]}
                  >
                    <Text
                      variant="caption"
                      style={{
                        fontWeight: "600",
                        color: isSelected ? "#fff" : colors.textSecondary,
                      }}
                    >
                      ₹{p >= 100_000 ? `${p / 100_000}L` : `${p / 1000}k`}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </Card>

          {/* 2. TIGHT SL BUFFER PERCENTAGE */}
          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Tight Stop-Loss Buffer %</Text>
                  <Badge
                    label={swingSlEnabled ? "Bypassed by Swing SL" : `${numBuffer}% Active`}
                    tone={swingSlEnabled ? "neutral" : "warning"}
                  />
                </View>
                <Text variant="caption" tone="secondary">
                  Buffer added to the raw tight stop loss to prevent early stop-outs from intraday volatility noise.
                </Text>
              </View>
            </View>

            {/* Inactive notice when Swing SL is active */}
            {swingSlEnabled && (
              <View
                style={{
                  backgroundColor: "rgba(245, 158, 11, 0.10)",
                  borderColor: "rgba(245, 158, 11, 0.35)",
                  borderWidth: 1,
                  borderRadius: 8,
                  padding: spacing.sm,
                  marginBottom: spacing.md,
                  gap: 4,
                }}
              >
                <Text variant="caption" style={{ color: colors.warning, fontWeight: "700" }}>
                  ⚠️ Inactive — Bypassed by Structural Swing Stop-Loss
                </Text>
                <Text variant="caption" tone="secondary">
                  Structural Swing Stop-Loss is currently enabled below. Trades set their stop-loss directly to the nearest intraday swing high/low instead of using this tight SL buffer. Either Swing SL or Tight SL Buffer works — never both stacked together.
                </Text>
              </View>
            )}

            <View style={[styles.formRow, swingSlEnabled && { opacity: 0.45, pointerEvents: "none" as const }]}>
              <View style={{ flex: 1 }}>
                <Input
                  label="SL Buffer Percentage (%)"
                  value={slBuffer}
                  onChangeText={setSlBuffer}
                  keyboardType="numeric"
                  placeholder="25"
                  rightElement={
                    <Text variant="caption" tone="muted" style={{ paddingRight: spacing.sm }}>
                      %
                    </Text>
                  }
                />
              </View>

              <View style={[styles.statBox, { flex: 2 }]}>
                <Text variant="caption" tone="muted">Buffer Formula</Text>
                <Text variant="caption" style={{ color: colors.textPrimary, fontWeight: "600" }}>
                  {swingSlEnabled
                    ? "Bypassed: Swing SL level used instead"
                    : `BUY: Tight SL − (Risk × ${numBuffer}%) | SELL: Tight SL + (Risk × ${numBuffer}%)`}
                </Text>
              </View>
            </View>

            {/* Buffer Preset Chips */}
            <View style={[styles.presetsRow, swingSlEnabled && { opacity: 0.45, pointerEvents: "none" as const }]}>
              <Text variant="caption" tone="muted" style={{ marginRight: spacing.xs }}>
                Presets:
              </Text>
              {SL_BUFFER_PRESETS.map((b) => {
                const isSelected = numBuffer === b;
                return (
                  <Pressable
                    key={b}
                    onPress={() => setSlBuffer(String(b))}
                    style={({ hovered }: any) => [
                      styles.chip,
                      isSelected && styles.chipActive,
                      hovered && !isSelected && styles.chipHovered,
                    ]}
                  >
                    <Text
                      variant="caption"
                      style={{
                        fontWeight: "600",
                        color: isSelected ? "#fff" : colors.textSecondary,
                      }}
                    >
                      {b}%
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </Card>

          {/* 2B. SWING-BASED STRUCTURAL SL */}
          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Structural Swing Stop-Loss</Text>
                  <Badge
                    label={swingSlEnabled ? "🟢 Active (Overrides Tight Buffer)" : "Off"}
                    tone={swingSlEnabled ? "positive" : "neutral"}
                  />
                </View>
                <Text variant="caption" tone="secondary">
                  When enabled, this overrides the Tight Stop-Loss Buffer above. Stop-loss is set purely to the nearest intraday swing high (for shorts) or swing low (for longs) detected from Fyers 5-min candles + your swing buffer %. Either Swing SL or Tight SL Buffer works — never both.
                </Text>
              </View>
            </View>

            {/* Toggle row */}
            <View style={[styles.formRow, { justifyContent: "space-between", alignItems: "center" }]}>
              <View style={{ flex: 1 }}>
                <Text variant="bodyStrong" style={{ color: colors.textPrimary }}>
                  Enable Swing-Based SL
                </Text>
                <Text variant="caption" tone="secondary">
                  Overrides flat tight SL with nearest structural swing level from today's 5-min chart (bypasses tight SL buffer).
                </Text>
              </View>
              <Switch
                value={swingSlEnabled}
                onValueChange={setSwingSlEnabled}
                trackColor={{ false: colors.borderSubtle, true: colors.accent }}
                thumbColor={swingSlEnabled ? "#fff" : colors.textMuted}
              />
            </View>

            {/* Buffer % input — only relevant when enabled */}
            {swingSlEnabled && (
              <View style={styles.formRow}>
                <View style={{ flex: 1 }}>
                  <Input
                    label="Swing SL Buffer % (added on top of swing level)"
                    value={swingSlBuffer}
                    onChangeText={setSwingSlBuffer}
                    keyboardType="numeric"
                    placeholder="1"
                    rightElement={
                      <Text variant="caption" tone="muted" style={{ paddingRight: spacing.sm }}>%</Text>
                    }
                  />
                </View>

                <View style={[styles.statBox, { flex: 2 }]}>
                  <Text variant="caption" tone="muted">How it works</Text>
                  <Text variant="caption" style={{ color: colors.textPrimary, fontWeight: "600" }}>
                    BUY: Swing Low × (1 − {swingSlBuffer}%) | SELL: Swing High × (1 + {swingSlBuffer}%) — tight SL buffer bypassed
                  </Text>
                </View>
              </View>
            )}

            {/* Buffer preset chips */}
            {swingSlEnabled && (
              <View style={styles.presetsRow}>
                <Text variant="caption" tone="muted" style={{ marginRight: spacing.xs }}>Presets:</Text>
                {[0.5, 1, 1.5, 2, 3, 5].map((b) => {
                  const cur = Number(swingSlBuffer) || 1;
                  const isSelected = Math.abs(cur - b) < 0.01;
                  return (
                    <Pressable
                      key={b}
                      onPress={() => setSwingSlBuffer(String(b))}
                      style={({ hovered }: any) => [
                        styles.chip,
                        isSelected && styles.chipActive,
                        hovered && !isSelected && styles.chipHovered,
                      ]}
                    >
                      <Text
                        variant="caption"
                        style={{ fontWeight: "600", color: isSelected ? "#fff" : colors.textSecondary }}
                      >
                        {b}%
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            )}

            {/* Info box when disabled */}
            {!swingSlEnabled && (
              <View style={[styles.statBox, { flexDirection: "row", alignItems: "center", gap: spacing.sm }]}>
                <Text variant="caption" tone="muted" style={{ flex: 1 }}>
                  💡 With Swing SL off, the system uses the strategy's raw tight SL + the buffer % above.
                  Enable this to anchor SL to real price structure (e.g. the 10:25 swing high for a short).
                </Text>
              </View>
            )}
          </Card>

          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Target Watchlist for Trading</Text>
                  <Badge label="Execution Scope" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  Choose which watchlist automated trades should execute for. When triggered, stocks from this list are bought in Paper or Fyers.
                </Text>
              </View>
            </View>

            <View style={styles.watchlistsGrid}>
              {/* Option: All Watchlists */}
              <Pressable
                onPress={() => setSelectedWatchlist("all")}
                style={({ hovered }: any) => [
                  styles.watchlistOptionCard,
                  selectedWatchlist === "all" && styles.watchlistOptionCardActive,
                  hovered && selectedWatchlist !== "all" && styles.watchlistOptionCardHovered,
                ]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                  <Text
                    variant="subtitle"
                    style={{
                      color: selectedWatchlist === "all" ? colors.accent : colors.textPrimary,
                    }}
                  >
                    🌐 All Watchlists
                  </Text>
                  <Badge label="Default" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  Scan and execute trades triggered in any of your active watchlists.
                </Text>
              </Pressable>

              {/* Individual user watchlists */}
              {watchlists.map((wl) => {
                const isSelected = selectedWatchlist === wl.id;
                return (
                  <Pressable
                    key={wl.id}
                    onPress={() => setSelectedWatchlist(wl.id)}
                    style={({ hovered }: any) => [
                      styles.watchlistOptionCard,
                      isSelected && styles.watchlistOptionCardActive,
                      hovered && !isSelected && styles.watchlistOptionCardHovered,
                    ]}
                  >
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                      <Text
                        variant="subtitle"
                        style={{
                          color: isSelected ? colors.accent : colors.textPrimary,
                        }}
                      >
                        📋 {wl.name}
                      </Text>
                      <Badge label={`${wl.itemCount} stocks`} tone={isSelected ? "positive" : "neutral"} />
                    </View>
                    <Text variant="caption" tone="secondary">
                      Limit trade executions strictly to setups originating in this list.
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </Card>

          {/* 3B. STRATEGY ENTRY TRIGGER MODE */}
          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Strategy Entry Trigger Mode</Text>
                  <Badge label="Entry Execution" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  Controls when auto-trade and alerts fire after a pullback support candle is formed.
                </Text>
              </View>
            </View>

            <View style={styles.watchlistsGrid}>
              <Pressable
                onPress={() => setEntryMode("close")}
                style={({ hovered }: any) => [
                  styles.watchlistOptionCard,
                  entryMode === "close" && styles.watchlistOptionCardActive,
                  hovered && entryMode !== "close" && styles.watchlistOptionCardHovered,
                ]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                  <Text
                    variant="subtitle"
                    style={{
                      color: entryMode === "close" ? colors.accent : colors.textPrimary,
                    }}
                  >
                    🕯️ 3m Candle Close (Confirmed)
                  </Text>
                  {entryMode === "close" && <Badge label="Active" tone="positive" />}
                </View>
                <Text variant="caption" tone="secondary">
                  Triggers only when a 3-minute candle confirms close beyond the support trigger price. Filters noise and false breakout wicks.
                </Text>
              </Pressable>

              <Pressable
                onPress={() => setEntryMode("touch")}
                style={({ hovered }: any) => [
                  styles.watchlistOptionCard,
                  entryMode === "touch" && styles.watchlistOptionCardActive,
                  hovered && entryMode !== "touch" && styles.watchlistOptionCardHovered,
                ]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                  <Text
                    variant="subtitle"
                    style={{
                      color: entryMode === "touch" ? colors.accent : colors.textPrimary,
                    }}
                  >
                    ⚡ LTP Touch / Break (Fast)
                  </Text>
                  {entryMode === "touch" && <Badge label="Active" tone="positive" />}
                </View>
                <Text variant="caption" tone="secondary">
                  Triggers immediately as soon as the live price tick (LTP) touches or crosses the support trigger level. Fast execution without waiting for candle close.
                </Text>
              </Pressable>
            </View>
          </Card>

          {/* 4. RISK MANAGEMENT & POSITIONS LIMITS */}
          <Card elevated style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 18 }}>Risk & Concurrent Position Limits</Text>
                  <Badge label="Strict Protection" tone="negative" />
                </View>
                <Text variant="caption" tone="secondary">
                  Enforces mathematical guardrails so no trade risks more than your threshold, and limits simultaneous exposure.
                </Text>
              </View>
            </View>

            <View style={styles.formRow}>
              <View style={{ flex: 1 }}>
                <Input
                  label="Max Risk / Trade (₹)"
                  value={maxRisk}
                  onChangeText={setMaxRisk}
                  keyboardType="numeric"
                  placeholder="1100"
                  rightElement={
                    <Text variant="caption" tone="muted" style={{ paddingRight: spacing.sm }}>
                      INR
                    </Text>
                  }
                />
              </View>

              <View style={{ flex: 1 }}>
                <Input
                  label="Max Concurrent Positions"
                  value={maxPositions}
                  onChangeText={setMaxPositions}
                  keyboardType="numeric"
                  placeholder="10"
                  rightElement={
                    <Text variant="caption" tone="muted" style={{ paddingRight: spacing.sm }}>
                      stocks
                    </Text>
                  }
                />
              </View>
            </View>

            <View style={styles.presetsRow}>
              <Text variant="caption" tone="muted" style={{ marginRight: spacing.xs }}>
                Risk Presets:
              </Text>
              {RISK_PRESETS.map((r) => {
                const isSelected = numRisk === r;
                return (
                  <Pressable
                    key={r}
                    onPress={() => setMaxRisk(String(r))}
                    style={({ hovered }: any) => [
                      styles.chip,
                      isSelected && styles.chipActive,
                      hovered && !isSelected && styles.chipHovered,
                    ]}
                  >
                    <Text
                      variant="caption"
                      style={{
                        fontWeight: "600",
                        color: isSelected ? "#fff" : colors.textSecondary,
                      }}
                    >
                      ₹{r}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </Card>

          {/* 5. LIVE SIZING CALCULATOR PREVIEW */}
          <Card elevated style={[styles.card, { borderColor: colors.accentMuted, backgroundColor: colors.surfaceElevated }]}>
            <View style={styles.cardHeader}>
              <View style={{ gap: 2, flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text variant="title" style={{ fontSize: 16 }}>Live Sizing Calculation Preview</Text>
                  <Badge label="Sample: KEI Industries" tone="neutral" />
                </View>
                <Text variant="caption" tone="secondary">
                  Based on your current settings, here is how an incoming trade is automatically calculated:
                </Text>
              </View>
            </View>

            <View style={styles.previewGrid}>
              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Stock Entry</Text>
                <Text variant="mono" style={{ color: colors.textPrimary }}>₹{sampleEntry.toFixed(2)}</Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Raw Tight SL</Text>
                <Text variant="mono" tone="warning">₹{sampleTightSl.toFixed(2)}</Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Buffered SL ({numBuffer}%)</Text>
                <Text variant="mono" tone="negative">₹{sampleBufferedSl.toFixed(2)}</Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Risk / Share</Text>
                <Text variant="mono">₹{sampleRiskPerShare.toFixed(2)}</Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Calculated Qty</Text>
                <Text variant="mono" tone="accent" style={{ fontWeight: "700", fontSize: 16 }}>
                  {sampleFinalQty} shares
                </Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Margin Required (5x)</Text>
                <Text variant="mono">₹{sampleMarginRequired.toFixed(2)}</Text>
              </View>

              <View style={styles.previewItem}>
                <Text variant="caption" tone="muted">Total Trade SL Risk</Text>
                <Text variant="mono" tone={sampleTotalRisk <= numRisk ? "positive" : "negative"}>
                  ₹{sampleTotalRisk.toFixed(2)} (≤ ₹{numRisk})
                </Text>
              </View>
            </View>
          </Card>

          {/* Footer Save & Reset Bar */}
          <View style={styles.footerRow}>
            <Button
              label="Reset Defaults"
              variant="secondary"
              onPress={handleReset}
            />

            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md }}>
              {saveSuccess ? (
                <Text variant="bodyStrong" tone="positive">
                  ✓ Settings saved successfully!
                </Text>
              ) : null}
              <Button
                label={updateMutation.isPending ? "Saving…" : "Save Settings"}
                onPress={handleSave}
                loading={updateMutation.isPending}
                size="md"
              />
            </View>
          </View>
        </View>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  scrollContent: {
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
  },
  container: {
    width: "100%",
    maxWidth: layout.narrowMaxWidth + 160,
    gap: spacing.lg,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: spacing.md,
    paddingBottom: spacing.sm,
  },
  backBtn: {
    alignSelf: "flex-start",
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    marginBottom: spacing.xs,
  },
  actionsTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  card: {
    gap: spacing.md,
    padding: spacing.xl,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  formRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    flexWrap: "wrap",
  },
  statBox: {
    flex: 1,
    minWidth: 140,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    gap: 4,
  },
  presetsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    flexWrap: "wrap",
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.full,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  chipHovered: {
    borderColor: colors.accent,
  },
  chipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  watchlistsGrid: {
    gap: spacing.sm,
  },
  watchlistOptionCard: {
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    gap: 6,
  },
  watchlistOptionCardHovered: {
    borderColor: colors.accent,
    backgroundColor: colors.surfaceHover,
  },
  watchlistOptionCardActive: {
    borderColor: colors.accent,
    backgroundColor: "rgba(91, 139, 255, 0.12)",
  },
  previewGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  previewItem: {
    flex: 1,
    minWidth: 120,
    gap: 4,
  },
  footerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
  },
});
