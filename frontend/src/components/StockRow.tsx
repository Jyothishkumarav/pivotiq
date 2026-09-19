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

  // Re-derive trend and VWAP delta from the LIVE LTP (item.ltp) rather than the
  // snapshot's currentPrice (which is the last 5-min candle close and may be stale).
  const liveTrend: IntradaySnapshot["trend"] | null = intraday && item.ltp !== null
    ? item.ltp > intraday.openingRangeHigh
      ? "up"
      : item.ltp < intraday.openingRangeLow
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
          {/* Symbol column */}
          <View style={{ flex: isDesktop ? 1.4 : 1.2, gap: 2 }}>
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
            <Text variant="mono">{item.ltp !== null ? formatCurrency(item.ltp) : "—"}</Text>
          </View>

          {/* Day column: day change on top, vs-VWAP caption below */}
          <View style={{ flex: 0.7, alignItems: "flex-end", gap: 2 }}>
            {item.changePercent !== null ? (
              <Text variant="mono" tone={isUp ? "positive" : "negative"}>
                {formatPercent(item.changePercent)}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
            {intraday && intraday.vwap > 0 && item.ltp !== null ? (
              (() => {
                const vwapDelta = ((item.ltp - intraday.vwap) / intraday.vwap) * 100;
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
                {formatCurrency(intraday.openingRangeHigh)}
              </Text>
            ) : (
              <Text variant="mono" tone="muted">
                —
              </Text>
            )}
          </View>

          {/* Stop Loss column: tight stop + risk delta, macro stop below */}
          <View style={{ flex: 1.45, alignItems: "flex-end", gap: 2 }}>
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") ? (
              (() => {
                const setup = intraday.tradeSetup;
                const hasTrigger = setup.triggerPrice !== null;
                const entryPrice = hasTrigger ? setup.triggerPrice! : setup.entry;
                const tightDelta = Math.abs(entryPrice - setup.stopLoss);
                const hasWideSl = setup.slWide != null;
                const wideDelta = hasWideSl ? Math.abs(entryPrice - setup.slWide!) : null;

                return (
                  <>
                    {/* Line 1: Tight stop + risk Δ */}
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

                    {/* Line 2: Macro stop + macro risk Δ */}
                    {hasWideSl ? (
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
                    ) : (
                      <Text variant="caption" tone="muted" style={{ fontSize: 10, lineHeight: 12 }} numberOfLines={1}>
                        Tight stop
                      </Text>
                    )}
                  </>
                );
              })()
            ) : intraday ? (
              <Text variant="caption" tone="muted" numberOfLines={1}>
                {formatCurrency(intraday.openingRangeLow)}
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
                const ref = item.ltp ?? intraday.currentPrice;
                const diff = ref - intraday.tradeSetup.entry;
                const pct = intraday.tradeSetup.entry > 0
                  ? (diff / intraday.tradeSetup.entry) * 100
                  : 0;
                const near = Math.abs(pct) < 0.05;
                // Once triggered, this is purely "is price now favorable vs.
                // entry" — NOT the setup's own lifecycle status (already
                // handled above), so avoid words like "waiting"/"triggered"
                // here that would collide with that unrelated meaning.
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
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") && item.ltp !== null ? (
              (() => {
                const rawDiff = item.ltp - intraday.tradeSetup.entry;
                const signedDiff = intraday.tradeSetup.action === "sell" ? -rawDiff : rawDiff;
                const pct = intraday.tradeSetup.entry > 0
                  ? (signedDiff / intraday.tradeSetup.entry) * 100
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
            {intraday?.tradeSetup && (intraday.tradeSetup.status === "triggered" || intraday.tradeSetup.status === "sl_hit") && item.ltp !== null ? (
              (() => {
                const rawGap = item.ltp - intraday.tradeSetup.stopLoss;
                const roomToSl = intraday.tradeSetup.action === "sell" ? -rawGap : rawGap;
                const pct = intraday.tradeSetup.stopLoss > 0
                  ? (roomToSl / intraday.tradeSetup.stopLoss) * 100
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

          {/* Time column: when the entry level was actually crossed */}
          <View style={{ flex: 0.6, alignItems: "flex-end" }}>
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
            {item.belowAllSupports ? (
              <View style={{ alignSelf: "flex-end" }}>
                <Badge label="Below supports" tone="warning" />
              </View>
            ) : item.distanceToSupportPercent !== null ? (
              <View style={{ alignItems: "flex-end", gap: 2 }}>
                <Text variant="mono">{formatPercent(item.distanceToSupportPercent)}</Text>
                {item.nearestSupport !== null ? (
                  <Text variant="caption" tone="muted">
                    from {formatCurrency(item.nearestSupport)}
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
