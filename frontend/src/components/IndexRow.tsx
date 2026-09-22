import React from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { Card, Text } from "@/components/ui";
import { colors, layout, spacing } from "@/theme/tokens";
import { IntradaySnapshot, TradeSetup } from "@/types";
import { formatCurrency, formatIstTime, formatPercent } from "@/utils/format";

interface Props {
  name: string;
  symbol: string;
  intraday?: IntradaySnapshot | null;
  accentColor?: string;
  onPress?: () => void;
}

const TREND_META = {
  up: { color: "#3DDB9F", glyph: "▲", label: "Above range" },
  down: { color: "#FF6B85", glyph: "▼", label: "Below range" },
  flat: { color: "#9AA9C7", glyph: "◆", label: "In range" },
} as const;

const SETUP_PILL_META = {
  buy: { color: "#3DDB9F", label: "BUY" },
  sell: { color: "#FF6B85", label: "SELL" },
} as const;

function TrendDot({ trend }: { trend: IntradaySnapshot["trend"] }) {
  const meta = TREND_META[trend];
  return (
    <View
      style={{
        width: 20,
        height: 20,
        borderRadius: 999,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: `${meta.color}22`,
        borderWidth: 1,
        borderColor: `${meta.color}55`,
      }}
    >
      <Text style={{ color: meta.color, fontSize: 10, lineHeight: 12 }}>{meta.glyph}</Text>
    </View>
  );
}

function SetupPill({ setup }: { setup: TradeSetup }) {
  const meta =
    setup.status === "waiting"
      ? { color: "#F5B54A", label: "WAIT" }
      : SETUP_PILL_META[setup.action];
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 999,
        backgroundColor: `${meta.color}22`,
        borderWidth: 1,
        borderColor: `${meta.color}66`,
      }}
    >
      <Text style={{ color: meta.color, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 }}>
        {meta.label}
      </Text>
    </View>
  );
}

export function IndexRow({ name, symbol, intraday, accentColor = colors.accent, onPress }: Props) {
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === "web" && width >= layout.wideBreakpoint;

  const effectiveLtp = intraday?.currentPrice ?? null;
  const dayChangePct = intraday?.changePercent ?? null;
  const isUp = (dayChangePct ?? 0) >= 0;

  const liveTrend: IntradaySnapshot["trend"] | null = intraday && effectiveLtp !== null
    ? effectiveLtp > intraday.openingRangeHigh
      ? "up"
      : effectiveLtp < intraday.openingRangeLow
        ? "down"
        : "flat"
    : intraday?.trend ?? null;

  return (
    <Pressable onPress={onPress}>
      {({ hovered }: any) => (
        <Card
          padded={false}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.lg,
            paddingVertical: spacing.md,
            borderColor: hovered ? accentColor : "rgba(255,255,255,0.08)",
            backgroundColor: hovered
              ? "rgba(255,255,255,0.04)"
              : "rgba(18, 24, 38, 0.75)",
            borderLeftWidth: 3,
            borderLeftColor: accentColor,
            marginBottom: 3,
          }}
        >
          {/* Symbol + intraday subtext */}
          <View style={{ flex: 1.4, gap: 2 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              {liveTrend ? <TrendDot trend={liveTrend} /> : null}
              <Text variant="subtitle" style={{ fontWeight: "700", letterSpacing: 0.2 }}>
                {name}
              </Text>
            </View>
            <Text variant="caption" tone="muted" numberOfLines={1}>
              {intraday
                ? `VWAP ${Math.round(intraday.vwap)} · ORB ${Math.round(intraday.openingRangeLow)}–${Math.round(intraday.openingRangeHigh)}`
                : "NSE Benchmark Index"}
            </Text>
          </View>

          {/* LTP column */}
          <View style={{ flex: 0.75, alignItems: "flex-end" }}>
            <Text variant="mono" style={{ fontWeight: "700" }}>
              {effectiveLtp !== null ? formatCurrency(effectiveLtp) : "—"}
            </Text>
          </View>

          {/* Day column: day change on top, vs-VWAP caption below */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {dayChangePct !== null ? (
              <Text variant="mono" tone={isUp ? "positive" : "negative"} style={{ fontWeight: "600" }}>
                {formatPercent(dayChangePct)}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
            {intraday && intraday.vwap > 0 && effectiveLtp !== null ? (
              (() => {
                const vwapDelta = ((effectiveLtp - intraday.vwap) / intraday.vwap) * 100;
                const vwapUp = vwapDelta >= 0;
                return (
                  <Text variant="caption" tone={vwapUp ? "positive" : "negative"} numberOfLines={1}>
                    V {formatPercent(vwapDelta)}
                  </Text>
                );
              })()
            ) : null}
          </View>

          {/* Setup column: pill only */}
          <View style={{ flex: 0.65, alignItems: "flex-end" }}>
            {intraday?.tradeSetup ? (
              <SetupPill setup={intraday.tradeSetup} />
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Entry column */}
          <View style={{ flex: 0.85, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup &&
            (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") ? (
              (() => {
                const setup = intraday.tradeSetup;
                const hasTrigger = setup.triggerPrice !== null;
                const entryPrice = hasTrigger ? setup.triggerPrice! : setup.entry;
                const breakoutPrice = hasTrigger && setup.triggerPrice !== setup.entry ? setup.entry : null;
                return (
                  <>
                    <Text variant="mono" tone="positive" style={{ fontSize: 12, lineHeight: 15, fontWeight: "600" }}>
                      {formatCurrency(entryPrice)}
                    </Text>
                    {breakoutPrice !== null ? (
                      <Text variant="caption" tone="muted" style={{ fontSize: 10, lineHeight: 12 }} numberOfLines={1}>
                        BO {formatCurrency(breakoutPrice)}
                      </Text>
                    ) : (
                      <Text variant="caption" tone="muted" style={{ fontSize: 10, lineHeight: 12 }} numberOfLines={1}>
                        Filled
                      </Text>
                    )}
                  </>
                );
              })()
            ) : intraday?.tradeSetup?.status === "pending_entry" ? (
              <>
                <Text variant="caption" tone="warning" numberOfLines={1}>
                  Watch PB
                </Text>
                {intraday.tradeSetup.triggerPrice !== null ? (
                  <Text variant="mono" tone="muted" style={{ fontSize: 11, lineHeight: 13 }} numberOfLines={1}>
                    {formatCurrency(intraday.tradeSetup.triggerPrice)}
                  </Text>
                ) : null}
              </>
            ) : intraday ? (
              <Text variant="caption" tone="muted" numberOfLines={1}>
                {formatCurrency(
                  intraday.tradeSetup?.action === "sell"
                    ? intraday.openingRangeLow
                    : intraday.openingRangeHigh
                )}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Stop Loss column: tight stop + risk delta, macro stop below */}
          <View style={{ flex: 1.45, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup &&
            (intraday.tradeSetup.status === "triggered" ||
              intraday.tradeSetup.status === "sl_hit" ||
              intraday.tradeSetup.status === "pending_entry") ? (
              (() => {
                const setup = intraday.tradeSetup;
                const hasTrigger = setup.triggerPrice !== null;
                const entryPrice = hasTrigger ? setup.triggerPrice! : setup.entry;
                const tightDelta = Math.abs(entryPrice - setup.stopLoss);
                const hasWideSl =
                  setup.slWide != null && Math.abs(setup.slWide - setup.stopLoss) > 0.05;
                const wideDelta = hasWideSl ? Math.abs(entryPrice - setup.slWide!) : null;

                return (
                  <>
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "flex-end", flexWrap: "nowrap", gap: 5 }}>
                      <Text variant="mono" tone="negative" style={{ fontSize: 11, lineHeight: 14 }} numberOfLines={1}>
                        SL {formatCurrency(setup.stopLoss)}
                      </Text>
                      <Text style={{ fontSize: 10, lineHeight: 12, fontWeight: "600", color: "#F5B54A" }} numberOfLines={1}>
                        Δ{formatCurrency(tightDelta)}
                      </Text>
                    </View>

                    {hasWideSl && (
                      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "flex-end", flexWrap: "nowrap", gap: 5, opacity: 0.85 }}>
                        <Text variant="mono" tone="negative" style={{ fontSize: 10, lineHeight: 12 }} numberOfLines={1}>
                          MSL {formatCurrency(setup.slWide!)}
                        </Text>
                        <Text style={{ fontSize: 10, lineHeight: 12, fontWeight: "600", color: "#F5B54A" }} numberOfLines={1}>
                          MΔ{formatCurrency(wideDelta!)}
                        </Text>
                      </View>
                    )}
                  </>
                );
              })()
            ) : intraday ? (
              <Text variant="caption" tone="muted" numberOfLines={1}>
                {formatCurrency(
                  intraday.tradeSetup?.action === "sell"
                    ? intraday.openingRangeHigh
                    : intraday.openingRangeLow
                )}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Status column */}
          <View style={{ flex: 0.65, alignItems: "flex-end", paddingLeft: spacing.sm }}>
            {intraday?.tradeSetup ? (
              (() => {
                if (intraday.tradeSetup.status === "sl_hit") {
                  return (
                    <Text variant="caption" tone="negative" numberOfLines={1}>
                      SL hit
                    </Text>
                  );
                }
                if (intraday.tradeSetup.status === "waiting") {
                  return (
                    <Text variant="caption" tone="muted" numberOfLines={1}>
                      wait
                    </Text>
                  );
                }
                if (intraday.tradeSetup.status === "pending_entry") {
                  return (
                    <Text variant="caption" tone="warning" numberOfLines={1}>
                      pullback wait
                    </Text>
                  );
                }
                const ref = effectiveLtp ?? intraday.currentPrice;
                const tradeEntry = intraday.tradeSetup.triggerPrice ?? intraday.tradeSetup.entry;
                const diff = ref - tradeEntry;
                const pct = tradeEntry > 0 ? (diff / tradeEntry) * 100 : 0;
                const near = Math.abs(pct) < 0.05;
                const inFavor =
                  (intraday.tradeSetup.action === "buy" && diff > 0) ||
                  (intraday.tradeSetup.action === "sell" && diff < 0);
                const tone: "positive" | "negative" | "warning" | "muted" = near
                  ? "warning"
                  : inFavor
                    ? "positive"
                    : "muted";
                const label = near ? "at entry" : inFavor ? "in profit" : "against";
                return (
                  <Text variant="caption" tone={tone} numberOfLines={1}>
                    {label}
                  </Text>
                );
              })()
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Δ Entry column */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup &&
            (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") &&
            effectiveLtp !== null ? (
              (() => {
                const tradeEntry = intraday.tradeSetup.triggerPrice ?? intraday.tradeSetup.entry;
                const rawDiff = effectiveLtp - tradeEntry;
                const signedDiff = intraday.tradeSetup.action === "sell" ? -rawDiff : rawDiff;
                const pct = tradeEntry > 0 ? (signedDiff / tradeEntry) * 100 : 0;
                const tone: "positive" | "negative" | "muted" =
                  pct > 0.05 ? "positive" : pct < -0.05 ? "negative" : "muted";
                const sign = signedDiff > 0 ? "+" : signedDiff < 0 ? "−" : "";
                return (
                  <>
                    <Text variant="mono" tone={tone}>
                      {sign}{formatCurrency(Math.abs(signedDiff))}
                    </Text>
                    <Text variant="caption" tone={tone}>
                      {formatPercent(pct)}
                    </Text>
                  </>
                );
              })()
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Δ SL column */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup &&
            (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") &&
            effectiveLtp !== null ? (
              (() => {
                const governingSl =
                  intraday.tradeSetup.slWide != null &&
                  Math.abs(intraday.tradeSetup.slWide - intraday.tradeSetup.stopLoss) > 0.05
                    ? intraday.tradeSetup.slWide
                    : intraday.tradeSetup.stopLoss;
                const rawGap = effectiveLtp - governingSl;
                const roomToSl = intraday.tradeSetup.action === "sell" ? -rawGap : rawGap;
                const pct = governingSl > 0 ? (roomToSl / governingSl) * 100 : 0;
                const tone: "positive" | "negative" | "warning" =
                  pct > 0.05 ? "positive" : pct < -0.05 ? "negative" : "warning";
                const sign = roomToSl > 0 ? "+" : roomToSl < 0 ? "−" : "";
                return (
                  <>
                    <Text variant="mono" tone={tone}>
                      {sign}{formatCurrency(Math.abs(roomToSl))}
                    </Text>
                    <Text variant="caption" tone={tone}>
                      {formatPercent(pct)}
                    </Text>
                  </>
                );
              })()
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Max Run column */}
          <View style={{ flex: 0.75, alignItems: "flex-end" }}>
            <Text variant="mono" tone="muted">
              —
            </Text>
          </View>

          {/* Time column */}
          <View style={{ flex: 0.65, alignItems: "flex-end" }}>
            {intraday?.tradeSetup?.triggeredAt ? (
              <Text variant="caption" tone="positive">
                {formatIstTime(intraday.tradeSetup.triggeredAt)}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Support column */}
          <View style={{ flex: 0.85, alignItems: "flex-end" }}>
            <Text variant="mono" tone="muted">
              —
            </Text>
          </View>

          {/* 42px spacer matching RemoveButton width in StockRow */}
          <View style={{ width: 42 }} />
        </Card>
      )}
    </Pressable>
  );
}
