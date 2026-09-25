import React, { useEffect, useState } from "react";
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
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
const SL_BUFFER_PRESETS = [15, 20, 25, 30, 35];
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
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (data) {
      setCapital(String(data.paperCapital || 100_000));
      setSlBuffer(String(data.slBufferPct || 25));
      setMaxRisk(String(data.maxRiskPerTrade || 1100));
      setMaxPositions(String(data.maxOpenPositions || 10));
      setSelectedWatchlist(data.activeWatchlistId || "all");
    }
  }, [data]);

  const updateMutation = useMutation({
    mutationFn: (payload: {
      paperCapital: number;
      slBufferPct: number;
      maxRiskPerTrade: number;
      maxOpenPositions: number;
      activeWatchlistId: string | null;
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
  const numBuffer = Math.max(1, Number(slBuffer) || 25);
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
    });
  };

  const handleReset = () => {
    setCapital("100000");
    setSlBuffer("25");
    setMaxRisk("1100");
    setMaxPositions("10");
    setSelectedWatchlist("all");
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
                  <Badge label={`${numBuffer}% Active`} tone="warning" />
                </View>
                <Text variant="caption" tone="secondary">
                  Buffer added to the raw tight stop loss to prevent early stop-outs from intraday volatility noise.
                </Text>
              </View>
            </View>

            <View style={styles.formRow}>
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
                  BUY: Tight SL − (Risk × {numBuffer}%) | SELL: Tight SL + (Risk × {numBuffer}%)
                </Text>
              </View>
            </View>

            {/* Buffer Preset Chips */}
            <View style={styles.presetsRow}>
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

          {/* 3. TARGET WATCHLIST FOR AUTO-TRADING */}
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
