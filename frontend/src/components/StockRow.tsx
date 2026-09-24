import React from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { Badge, Card, Text } from "@/components/ui";
import { colors, layout, radius, spacing } from "@/theme/tokens";
import { IntradaySnapshot, TradeSetup, WatchlistItem } from "@/types";
import { formatCurrency, formatIstTime, formatPercent } from "@/utils/format";

interface Props {
  item: WatchlistItem;
  intraday?: IntradaySnapshot | null;
  onPress?: () => void;
  onRemove?: () => void;
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
        width: 22,
        height: 22,
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
  // The Setup pill is always the direction (buy/sell) or wait — never "SL HIT".
  // Whether the trade already got stopped out lives in the separate Status column.
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

function RemoveButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable
      onPress={(e: any) => {
        e?.stopPropagation?.();
        onPress();
      }}
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

export function StockRow({ item, intraday, onPress, onRemove }: Props) {
  const isUp = (item.changePercent ?? 0) >= 0;
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === "web" && width >= layout.wideBreakpoint;

  // In retest mode, use the historical snapshot's currentPrice; otherwise prefer live LTP.
  const effectiveLtp = intraday?.retestDate ? intraday.currentPrice : (item.ltp ?? intraday?.currentPrice ?? null);

  // Re-derive trend and VWAP delta from the effective LTP.
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
            borderColor: hovered ? colors.border : colors.borderSubtle,
            backgroundColor: hovered ? colors.surfaceElevated : colors.surface,
          }}
        >
          {/* Symbol + intraday badge */}
          <View style={{ flex: 1.25, gap: 2 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              {liveTrend ? <TrendDot trend={liveTrend} /> : null}
              <Text variant="subtitle">{item.symbol}</Text>
            </View>
            <Text variant="caption" tone="muted" numberOfLines={1}>
              {intraday
                ? `VWAP ${Math.round(intraday.vwap)} · ORB ${Math.round(intraday.openingRangeLow)}–${Math.round(intraday.openingRangeHigh)}`
                : item.exchange}
            </Text>
          </View>

          {/* LTP column */}
          <View style={{ flex: 0.75, alignItems: "flex-end" }}>
            <Text variant="mono">{effectiveLtp !== null ? formatCurrency(effectiveLtp) : "—"}</Text>
          </View>

          {/* Day column: day change on top, vs-VWAP caption below */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {item.changePercent !== null && !intraday?.retestDate ? (
              <Text variant="mono" tone={isUp ? "positive" : "negative"}>
                {formatPercent(item.changePercent)}
              </Text>
            ) : intraday?.retestDate ? (
              <Text variant="caption" tone="muted">
                Session
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
                  <Text
                    variant="caption"
                    tone={vwapUp ? "positive" : "negative"}
                    numberOfLines={1}
                  >
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
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") ? (
              (() => {
                const setup = intraday.tradeSetup;
                const hasTrigger = setup.triggerPrice !== null;
                const entryPrice = hasTrigger ? setup.triggerPrice! : setup.entry;
                const breakoutPrice = hasTrigger && setup.triggerPrice !== setup.entry ? setup.entry : null;
                return (
                  <>
                    <Text variant="mono" tone="positive" style={{ fontSize: 12, lineHeight: 15 }}>
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
          <View style={{ flex: 1.35, alignItems: "flex-end", gap: 2, paddingRight: spacing.sm }}>
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit" || intraday.tradeSetup.status === "pending_entry") ? (
              (() => {
                const setup = intraday.tradeSetup;
                const hasTrigger = setup.triggerPrice !== null;
                const entryPrice = hasTrigger ? setup.triggerPrice! : setup.entry;
                const tightDelta = Math.abs(entryPrice - setup.stopLoss);
                const hasWideSl =
                  setup.slWide != null &&
                  Math.abs(setup.slWide - setup.stopLoss) > 0.05;
                const wideDelta = hasWideSl ? Math.abs(entryPrice - setup.slWide!) : null;

                return (
                  <>
                    {/* Line 1: Main stop + risk Δ */}
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "flex-end", flexWrap: "nowrap", gap: 5 }}>
                      <Text variant="mono" tone="negative" style={{ fontSize: 11, lineHeight: 14 }} numberOfLines={1}>
                        SL {formatCurrency(setup.stopLoss)}
                      </Text>
                      <Text
                        style={{ fontSize: 10, lineHeight: 12, fontWeight: "600", color: "#F5B54A" }}
                        numberOfLines={1}
                      >
                        Δ{formatCurrency(tightDelta)}
                      </Text>
                    </View>

                    {/* Line 2: Macro stop + macro risk Δ (only if different from primary SL) */}
                    {hasWideSl && (
                      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "flex-end", flexWrap: "nowrap", gap: 5, opacity: 0.85 }}>
                        <Text variant="mono" tone="negative" style={{ fontSize: 10, lineHeight: 12 }} numberOfLines={1}>
                          MSL {formatCurrency(setup.slWide!)}
                        </Text>
                        <Text
                          style={{ fontSize: 10, lineHeight: 12, fontWeight: "600", color: "#F5B54A" }}
                          numberOfLines={1}
                        >
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
          <View style={{ flex: 1.0, alignItems: "flex-end", paddingLeft: spacing.xs }}>
            {intraday?.tradeSetup ? (
              (() => {
                if (intraday.tradeSetup.stageLabel) {
                  const stage = intraday.tradeSetup.stage ?? 1;
                  let bg = "rgba(107, 114, 128, 0.15)";
                  let border = "rgba(107, 114, 128, 0.35)";
                  let textCol = "#9ca3af";

                  if (stage === 1) {
                    bg = "rgba(107, 114, 128, 0.15)";
                    border = "rgba(107, 114, 128, 0.35)";
                    textCol = "#9ca3af";
                  } else if (stage === 2) {
                    bg = "rgba(56, 189, 248, 0.15)";
                    border = "rgba(56, 189, 248, 0.35)";
                    textCol = "#38bdf8";
                  } else if (stage === 3) {
                    bg = "rgba(251, 191, 36, 0.15)";
                    border = "rgba(251, 191, 36, 0.35)";
                    textCol = "#fbbf24";
                  } else if (stage === 4) {
                    bg = "rgba(168, 85, 247, 0.15)";
                    border = "rgba(168, 85, 247, 0.35)";
                    textCol = "#c084fc";
                  } else if (stage === 5) {
                    bg = "rgba(34, 197, 94, 0.15)";
                    border = "rgba(34, 197, 94, 0.35)";
                    textCol = "#4ade80";
                  } else if (stage === 6) {
                    bg = "rgba(239, 68, 68, 0.15)";
                    border = "rgba(239, 68, 68, 0.35)";
                    textCol = "#f87171";
                  }

                  return (
                    <View style={{ alignItems: "flex-end", gap: 2 }}>
                      <View
                        style={{
                          backgroundColor: bg,
                          borderColor: border,
                          borderWidth: 1,
                          paddingHorizontal: 6,
                          paddingVertical: 2,
                          borderRadius: 4,
                        }}
                      >
                        <Text
                          style={{
                            color: textCol,
                            fontSize: 10,
                            fontWeight: "700",
                            letterSpacing: 0.3,
                            textTransform: "uppercase",
                          }}
                          numberOfLines={1}
                        >
                          {intraday.tradeSetup.stageLabel}
                        </Text>
                      </View>
                      {stage === 4 && intraday.tradeSetup.triggerPrice ? (
                        <Text variant="mono" tone="muted" style={{ fontSize: 9 }}>
                          brk ₹{intraday.tradeSetup.triggerPrice.toFixed(2)}
                        </Text>
                      ) : null}
                    </View>
                  );
                }

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
                const pct = tradeEntry > 0
                  ? (diff / tradeEntry) * 100
                  : 0;
                const near = Math.abs(pct) < 0.05;
                const inFavor =
                  (intraday.tradeSetup.action === "buy" && diff > 0) ||
                  (intraday.tradeSetup.action === "sell" && diff < 0);
                const tone: "positive" | "negative" | "warning" | "muted" = near
                  ? "warning"
                  : inFavor
                    ? "positive"
                    : "muted";
                const label = near
                  ? "at entry"
                  : inFavor
                    ? "in profit"
                    : "against";
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

          {/* Δ Entry column: signed ₹ + % — positive means trade is going in your favor */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") && effectiveLtp !== null ? (
              (() => {
                const tradeEntry = intraday.tradeSetup.triggerPrice ?? intraday.tradeSetup.entry;
                const rawDiff = effectiveLtp - tradeEntry;
                const signedDiff = intraday.tradeSetup.action === "sell" ? -rawDiff : rawDiff;
                const pct = tradeEntry > 0
                  ? (signedDiff / tradeEntry) * 100
                  : 0;
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

          {/* Δ SL column: room to stop loss (positive = safe, negative = past stop) */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") && effectiveLtp !== null ? (
              (() => {
                const governingSl =
                  intraday.tradeSetup.slWide != null &&
                  Math.abs(intraday.tradeSetup.slWide - intraday.tradeSetup.stopLoss) > 0.05
                    ? intraday.tradeSetup.slWide
                    : intraday.tradeSetup.stopLoss;
                const rawGap = effectiveLtp - governingSl;
                const roomToSl = intraday.tradeSetup.action === "sell" ? -rawGap : rawGap;
                const pct = governingSl > 0
                  ? (roomToSl / governingSl) * 100
                  : 0;
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

          {/* Max Run column: peak profit gained after trigger (₹ + %) */}
          <View style={{ flex: 0.75, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup &&
            (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") &&
            intraday.tradeSetup.maxFavorableDelta !== undefined &&
            intraday.tradeSetup.maxFavorableDelta !== null ? (
              <>
                <Text variant="mono" tone="positive">
                  +{formatCurrency(intraday.tradeSetup.maxFavorableDelta)}
                </Text>
                <Text variant="caption" tone="positive" numberOfLines={1}>
                  {formatPercent(intraday.tradeSetup.maxFavorablePercent ?? 0)}
                </Text>
              </>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Time column: trigger time on line 1, peak profit time on line 2 */}
          <View style={{ flex: 0.65, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup?.triggeredAt ? (
              <>
                <Text variant="caption" tone="positive" numberOfLines={1}>
                  {formatIstTime(intraday.tradeSetup.triggeredAt)}
                </Text>
                {intraday.tradeSetup.maxFavorableTime ? (
                  <Text variant="caption" tone="muted" numberOfLines={1} style={{ fontSize: 10 }}>
                    @{intraday.tradeSetup.maxFavorableTime}
                  </Text>
                ) : null}
              </>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Support column */}
          <View style={{ flex: 0.75, alignItems: "flex-end" }}>
            {item.belowAllSupports ? (
              <View style={{ alignSelf: "flex-end" }}>
                <Badge label="Below supports" tone="warning" />
              </View>
            ) : item.distanceToSupportPercent !== null ? (
              <View style={{ alignItems: "flex-end", gap: 2 }}>
                <Text variant="mono">{formatPercent(item.distanceToSupportPercent)}</Text>
                {item.nearestSupport !== null ? (
                  <Text variant="caption" tone="muted">
                    {formatCurrency(item.nearestSupport)}
                  </Text>
                ) : null}
              </View>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Remove */}
          {onRemove ? (
            <View style={{ width: 42, alignItems: "flex-end" }}>
              <RemoveButton onPress={onRemove} />
            </View>
          ) : null}
        </Card>
      )}
    </Pressable>
  );
}
