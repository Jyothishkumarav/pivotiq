import React from "react";
import { Text as RNText, TextProps, TextStyle } from "react-native";
import { colors, typography } from "@/theme/tokens";

type Variant = keyof typeof typography;
type Tone = "primary" | "secondary" | "muted" | "positive" | "negative" | "warning" | "accent";

const toneColor: Record<Tone, string> = {
  primary: colors.textPrimary,
  secondary: colors.textSecondary,
  muted: colors.textMuted,
  positive: colors.positiveText,
  negative: colors.negative,
  warning: colors.warning,
  accent: colors.accent,
};

interface Props extends TextProps {
  variant?: Variant;
  tone?: Tone;
  style?: TextStyle | TextStyle[];
}

export function Text({ variant = "body", tone = "primary", style, ...rest }: Props) {
  return <RNText style={[typography[variant], { color: toneColor[tone] }, style]} {...rest} />;
}
