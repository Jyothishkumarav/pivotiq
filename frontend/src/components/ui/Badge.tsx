import React from "react";
import { View } from "react-native";
import { colors, radius, spacing } from "@/theme/tokens";
import { Text } from "./Text";

type Tone = "positive" | "negative" | "warning" | "neutral";

const toneColors: Record<Tone, { bg: string; fg: string }> = {
  positive: { bg: colors.positiveBg, fg: colors.positiveText },
  negative: { bg: colors.negativeBg, fg: colors.negative },
  warning: { bg: colors.warningBg, fg: colors.warning },
  neutral: { bg: colors.accentMuted, fg: colors.accent },
};

export function Badge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  const c = toneColors[tone];
  return (
    <View
      style={{
        backgroundColor: c.bg,
        paddingHorizontal: spacing.sm,
        paddingVertical: 3,
        borderRadius: radius.full,
        alignSelf: "flex-start",
      }}
    >
      <Text variant="caption" style={{ color: c.fg }}>
        {label}
      </Text>
    </View>
  );
}
