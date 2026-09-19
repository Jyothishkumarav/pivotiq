import React, { useMemo, useState } from "react";
import { LayoutChangeEvent, View } from "react-native";
import Svg, { G, Line, Rect, Text as SvgText } from "react-native-svg";
import { Card, Text } from "@/components/ui";
import { colors, spacing } from "@/theme/tokens";
import { Candle, SupportLevelsResponse, SupportResistanceSet, SwingZone } from "@/types";
import { formatCurrency } from "@/utils/format";

export interface Overlay {
  value: number;
  label: string;
  tone: "support" | "resistance" | "pivot";
}

interface Props {
  candles: Candle[];
  overlays?: Overlay[];
  height?: number;
}

const PADDING = { top: 24, right: 68, bottom: 32, left: 12 };
const CANDLE_GAP = 2;
const HORIZONTAL_GRIDLINES = 5;

const OVERLAY_COLORS: Record<Overlay["tone"], string> = {
  support: colors.positive,
  resistance: colors.negative,
  pivot: colors.accent,
};

export function CandleChart({ candles, overlays = [], height = 380 }: Props) {
  const [width, setWidth] = useState(0);

  const onLayout = (e: LayoutChangeEvent) => {
    setWidth(e.nativeEvent.layout.width);
  };

  const model = useMemo(() => {
    if (candles.length === 0 || width === 0) return null;

    const priceLow = Math.min(
      ...candles.map((c) => c.low),
      ...overlays.map((o) => o.value),
    );
    const priceHigh = Math.max(
      ...candles.map((c) => c.high),
      ...overlays.map((o) => o.value),
    );
    const range = priceHigh - priceLow || 1;
    const pricePad = range * 0.05;
    const yMin = priceLow - pricePad;
    const yMax = priceHigh + pricePad;

    const plotW = width - PADDING.left - PADDING.right;
    const plotH = height - PADDING.top - PADDING.bottom;
    const candleW = Math.max(1, plotW / candles.length - CANDLE_GAP);

    const priceToY = (p: number) =>
      PADDING.top + plotH - ((p - yMin) / (yMax - yMin)) * plotH;
    const indexToX = (i: number) =>
      PADDING.left + i * (plotW / candles.length) + candleW / 2;

    return { candleW, plotW, plotH, priceToY, indexToX, yMin, yMax };
  }, [candles, overlays, width, height]);

  if (candles.length === 0) {
    return (
      <Card>
        <Text variant="body" tone="muted">
          No candle data available for this symbol.
        </Text>
      </Card>
    );
  }

  return (
    <View onLayout={onLayout} style={{ width: "100%", height }}>
      {model && width > 0 ? (
        <Svg width={width} height={height}>
          {/* Horizontal gridlines + price labels */}
          {Array.from({ length: HORIZONTAL_GRIDLINES }, (_, i) => {
            const price = model.yMin + ((model.yMax - model.yMin) * i) / (HORIZONTAL_GRIDLINES - 1);
            const y = model.priceToY(price);
            return (
              <G key={`grid-${i}`}>
                <Line
                  x1={PADDING.left}
                  x2={width - PADDING.right}
                  y1={y}
                  y2={y}
                  stroke={colors.divider}
                  strokeWidth={1}
                  strokeDasharray="4,4"
                />
                <SvgText
                  x={width - PADDING.right + 6}
                  y={y + 4}
                  fill={colors.textMuted}
                  fontSize="10"
                >
                  {formatCurrency(price)}
                </SvgText>
              </G>
            );
          })}

          {/* Candles */}
          {candles.map((c, i) => {
            const x = model.indexToX(i);
            const openY = model.priceToY(c.open);
            const closeY = model.priceToY(c.close);
            const highY = model.priceToY(c.high);
            const lowY = model.priceToY(c.low);
            const bullish = c.close >= c.open;
            const fill = bullish ? colors.positive : colors.negative;
            const bodyTop = Math.min(openY, closeY);
            const bodyH = Math.max(1, Math.abs(closeY - openY));
            return (
              <G key={c.time}>
                <Line
                  x1={x}
                  x2={x}
                  y1={highY}
                  y2={lowY}
                  stroke={fill}
                  strokeWidth={1}
                />
                <Rect
                  x={x - model.candleW / 2}
                  y={bodyTop}
                  width={model.candleW}
                  height={bodyH}
                  fill={fill}
                  opacity={bullish ? 0.9 : 1}
                />
              </G>
            );
          })}

          {/* S/R overlays */}
          {overlays.map((o, i) => {
            const y = model.priceToY(o.value);
            const stroke = OVERLAY_COLORS[o.tone];
            return (
              <G key={`overlay-${i}`}>
                <Line
                  x1={PADDING.left}
                  x2={width - PADDING.right}
                  y1={y}
                  y2={y}
                  stroke={stroke}
                  strokeWidth={1.5}
                  strokeDasharray="6,3"
                  opacity={0.85}
                />
                <SvgText
                  x={PADDING.left + 6}
                  y={y - 4}
                  fill={stroke}
                  fontSize="10"
                  fontWeight="bold"
                >
                  {o.label}
                </SvgText>
              </G>
            );
          })}

          {/* Date labels — first, middle, last */}
          {[0, Math.floor(candles.length / 2), candles.length - 1].map((i) => {
            const date = new Date(candles[i].time);
            const label = date.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
            return (
              <SvgText
                key={`date-${i}`}
                x={model.indexToX(i)}
                y={height - 12}
                fill={colors.textMuted}
                fontSize="10"
                textAnchor="middle"
              >
                {label}
              </SvgText>
            );
          })}
        </Svg>
      ) : null}
    </View>
  );
}

export type OverlayMethod = "classic" | "fibonacci" | "camarilla" | "woodie" | "swingLow" | "none";

export const OVERLAY_METHOD_LABELS: Record<OverlayMethod, string> = {
  classic: "Classic",
  fibonacci: "Fibonacci",
  camarilla: "Camarilla",
  woodie: "Woodie",
  swingLow: "Swing zones",
  none: "Off",
};

export function buildOverlays(levels: SupportLevelsResponse | undefined, method: OverlayMethod): Overlay[] {
  if (!levels || method === "none") return [];

  if (method === "swingLow") {
    return (levels.swingLowZones ?? []).map((z: SwingZone, idx: number) => ({
      value: z.level,
      label: `Zone ${idx + 1} · ${z.touchCount}×`,
      tone: "support" as const,
    }));
  }

  const pivotSet = levels.pivotMethods.find((p: SupportResistanceSet) => p.method === method);
  if (!pivotSet) return [];

  const items: Overlay[] = [];
  if (pivotSet.r3 !== null && pivotSet.r3 !== undefined)
    items.push({ value: pivotSet.r3, label: "R3", tone: "resistance" });
  if (pivotSet.r2 !== null) items.push({ value: pivotSet.r2, label: "R2", tone: "resistance" });
  if (pivotSet.r1 !== null) items.push({ value: pivotSet.r1, label: "R1", tone: "resistance" });
  items.push({ value: pivotSet.pivot, label: "Pivot", tone: "pivot" });
  if (pivotSet.s1 !== null) items.push({ value: pivotSet.s1, label: "S1", tone: "support" });
  if (pivotSet.s2 !== null) items.push({ value: pivotSet.s2, label: "S2", tone: "support" });
  if (pivotSet.s3 !== null && pivotSet.s3 !== undefined)
    items.push({ value: pivotSet.s3, label: "S3", tone: "support" });
  return items;
}
