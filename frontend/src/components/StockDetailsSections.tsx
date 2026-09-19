import React from "react";
import { View } from "react-native";
import { Badge, Card, Text } from "@/components/ui";
import { colors, spacing } from "@/theme/tokens";
import { StockDetails } from "@/types";
import { formatCompactCurrency, formatCurrency, formatPercent, formatRelativeTime } from "@/utils/format";

interface Props {
  details: StockDetails;
}

const RECOMMENDATION_TONE: Record<string, "positive" | "negative" | "warning" | "neutral"> = {
  strong_buy: "positive",
  buy: "positive",
  hold: "warning",
  sell: "negative",
  strong_sell: "negative",
};

function StatRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
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

function fmtCurrency(v: number | null | undefined): string | null {
  return v === null || v === undefined ? null : formatCurrency(v);
}

function fmtCompact(v: number | null | undefined): string | null {
  return v === null || v === undefined ? null : formatCompactCurrency(v);
}

function fmtNumber(v: number | null | undefined, digits = 2): string | null {
  return v === null || v === undefined ? null : v.toFixed(digits);
}

function fmtInt(v: number | null | undefined): string | null {
  return v === null || v === undefined ? null : v.toLocaleString("en-IN");
}

function fmtPct(v: number | null | undefined, isFraction = true): string | null {
  if (v === null || v === undefined) return null;
  const pct = isFraction ? v * 100 : v;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const rows = React.Children.toArray(children).filter(Boolean);
  if (rows.length === 0) return null;
  return (
    <Card style={{ gap: spacing.xs, flex: 1, minWidth: 260 }}>
      <Text variant="subtitle" style={{ marginBottom: spacing.sm }}>
        {title}
      </Text>
      {rows}
    </Card>
  );
}

export function StockDetailsSections({ details }: Props) {
  const { profile, price, valuation, market, profitability, balance, dividend, analyst } = details;

  const recommendation = analyst.recommendationKey?.toLowerCase() ?? null;
  const recommendationTone = recommendation ? RECOMMENDATION_TONE[recommendation] ?? "neutral" : "neutral";
  const isSnapshotOnly = details.source === "snapshot";

  return (
    <View style={{ gap: spacing.lg }}>
      {isSnapshotOnly ? (
        <Card
          style={{
            gap: spacing.xs,
            borderColor: colors.warning,
            backgroundColor: colors.warningBg,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <View style={{ width: 8, height: 8, borderRadius: 999, backgroundColor: colors.warning }} />
            <Text variant="bodyStrong" tone="warning">
              Showing snapshot only
            </Text>
          </View>
          <Text variant="caption" tone="secondary">
            Yahoo Finance is currently rate-limiting us (HTTP 429). Only fields present in the daily NSE
            snapshot are shown — price range, volume, and 52-week high/low. Valuation, profitability,
            balance sheet, moving averages, dividend and analyst data will populate once a Yahoo fetch
            succeeds. Try <Text variant="caption" tone="accent">Refresh from Yahoo</Text> after a few
            minutes.
          </Text>
        </Card>
      ) : null}

      {/* Profile band */}
      {(profile.shortName || profile.sector || profile.industry) && (
        <Card style={{ gap: spacing.xs }}>
          {profile.shortName ? <Text variant="subtitle">{profile.shortName}</Text> : null}
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, alignItems: "center" }}>
            {profile.sectorDisp || profile.sector ? (
              <Badge label={profile.sectorDisp ?? profile.sector ?? ""} tone="neutral" />
            ) : null}
            {profile.industryDisp || profile.industry ? (
              <Badge label={profile.industryDisp ?? profile.industry ?? ""} tone="neutral" />
            ) : null}
            <Text variant="caption" tone="muted">
              · source: {details.source} · updated {formatRelativeTime(details.updatedAt)}
            </Text>
          </View>
        </Card>
      )}

      {/* Two-column grid of sections */}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
        <Section title="Valuation">
          <StatRow label="Trailing P/E" value={fmtNumber(valuation.trailingPE)} />
          <StatRow label="Forward P/E" value={fmtNumber(valuation.forwardPE)} />
          <StatRow label="PEG (trailing)" value={fmtNumber(valuation.trailingPegRatio ?? valuation.pegRatio)} />
          <StatRow label="P/B" value={fmtNumber(valuation.priceToBook)} />
          <StatRow label="P/S (TTM)" value={fmtNumber(valuation.priceToSalesTrailing12Months)} />
          <StatRow label="Beta" value={fmtNumber(valuation.beta)} />
          <StatRow label="P/EPS (current FY)" value={fmtNumber(valuation.priceEpsCurrentYear)} />
        </Section>

        <Section title="Market cap & volume">
          <StatRow label="Market cap" value={fmtCompact(market.marketCap)} />
          <StatRow label="Non-diluted market cap" value={fmtCompact(market.nonDilutedMarketCap)} />
          <StatRow label="Volume (today)" value={fmtInt(market.volume)} />
          <StatRow label="Average volume (3M)" value={fmtInt(market.averageVolume)} />
          <StatRow label="Average volume (10D)" value={fmtInt(market.averageVolume10days)} />
        </Section>

        <Section title="Price range">
          <StatRow label="Open" value={fmtCurrency(price.open)} />
          <StatRow label="Day high" value={fmtCurrency(price.dayHigh)} />
          <StatRow label="Day low" value={fmtCurrency(price.dayLow)} />
          <StatRow label="Previous close" value={fmtCurrency(price.previousClose)} />
          <StatRow label="52-week high" value={fmtCurrency(price.fiftyTwoWeekHigh)} />
          <StatRow label="52-week low" value={fmtCurrency(price.fiftyTwoWeekLow)} />
          <StatRow label="All-time high" value={fmtCurrency(price.allTimeHigh)} />
          <StatRow label="All-time low" value={fmtCurrency(price.allTimeLow)} />
        </Section>

        <Section title="Moving averages">
          <StatRow label="50-day average" value={fmtCurrency(price.fiftyDayAverage)} />
          <StatRow label="200-day average" value={fmtCurrency(price.twoHundredDayAverage)} />
          <StatRow label="Δ vs 200-DMA" value={fmtCurrency(price.twoHundredDayAverageChange)} />
          <StatRow label="Δ% vs 200-DMA" value={fmtPct(price.twoHundredDayAverageChangePercent, false)} />
        </Section>

        <Section title="Profitability">
          <StatRow label="EPS (TTM)" value={fmtCurrency(profitability.trailingEps)} />
          <StatRow label="Profit margin" value={fmtPct(profitability.profitMargins)} />
          <StatRow label="Operating margin" value={fmtPct(profitability.operatingMargins)} />
          <StatRow label="Return on equity" value={fmtPct(profitability.returnOnEquity)} />
          <StatRow label="Return on assets" value={fmtPct(profitability.returnOnAssets)} />
          <StatRow label="Revenue / share" value={fmtCurrency(profitability.revenuePerShare)} />
          <StatRow label="Revenue growth (YoY)" value={fmtPct(profitability.revenueGrowth)} />
        </Section>

        <Section title="Balance sheet & cash flow">
          <StatRow label="Total revenue (TTM)" value={fmtCompact(balance.totalRevenue)} />
          <StatRow label="Total cash" value={fmtCompact(balance.totalCash)} />
          <StatRow label="Cash / share" value={fmtCurrency(balance.totalCashPerShare)} />
          <StatRow label="Total debt" value={fmtCompact(balance.totalDebt)} />
          <StatRow label="Operating cash flow" value={fmtCompact(balance.operatingCashflow)} />
          <StatRow label="Quick ratio" value={fmtNumber(balance.quickRatio)} />
        </Section>

        <Section title="Dividend">
          <StatRow label="Dividend rate" value={fmtCurrency(dividend.dividendRate)} />
          <StatRow
            label="Dividend yield"
            value={dividend.dividendYield !== null ? `${dividend.dividendYield.toFixed(2)}%` : null}
          />
        </Section>

        {analyst.numberOfAnalystOpinions ? (
          <Card style={{ gap: spacing.sm, flex: 1, minWidth: 260 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text variant="subtitle">Analyst view</Text>
              {recommendation ? (
                <Badge label={recommendation.replace("_", " ").toUpperCase()} tone={recommendationTone} />
              ) : null}
            </View>
            <StatRow label="Analysts covering" value={fmtInt(analyst.numberOfAnalystOpinions)} />
            <StatRow label="Consensus score (1=Buy)" value={fmtNumber(analyst.recommendationMean)} />
            <StatRow label="Target mean" value={fmtCurrency(analyst.targetMeanPrice)} />
            <StatRow label="Target median" value={fmtCurrency(analyst.targetMedianPrice)} />
            <StatRow label="Target low" value={fmtCurrency(analyst.targetLowPrice)} />
            <StatRow label="Target high" value={fmtCurrency(analyst.targetHighPrice)} />
          </Card>
        ) : null}
      </View>
    </View>
  );
}
