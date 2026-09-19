import React from "react";
import { View } from "react-native";
import { Card, Text } from "@/components/ui";
import { spacing } from "@/theme/tokens";
import { SupportResistanceSet } from "@/types";
import { formatCurrency } from "@/utils/format";

const METHOD_LABELS: Record<string, string> = {
  classic: "Classic Pivot",
  fibonacci: "Fibonacci",
  camarilla: "Camarilla",
  woodie: "Woodie",
};

function Row({ label, value }: { label: string; value: number | null }) {
  if (value === null) return null;
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Text variant="mono">{formatCurrency(value)}</Text>
    </View>
  );
}

export function SupportLevelCard({ set }: { set: SupportResistanceSet }) {
  return (
    <Card style={{ gap: spacing.sm }}>
      <Text variant="subtitle">{METHOD_LABELS[set.method] ?? set.method}</Text>
      <Row label="Resistance 3 (R3)" value={set.r3} />
      <Row label="Resistance 2 (R2)" value={set.r2} />
      <Row label="Resistance 1 (R1)" value={set.r1} />
      <Row label="Pivot" value={set.pivot} />
      <Row label="Support 1 (S1)" value={set.s1} />
      <Row label="Support 2 (S2)" value={set.s2} />
      <Row label="Support 3 (S3)" value={set.s3} />
    </Card>
  );
}
