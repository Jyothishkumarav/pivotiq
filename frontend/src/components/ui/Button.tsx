import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, ViewStyle } from "react-native";
import { colors, radius, spacing } from "@/theme/tokens";
import { Text } from "./Text";

type Variant = "primary" | "secondary" | "danger" | "ghost" | "buy" | "sell";
type Size = "sm" | "md";

interface Props {
  label: string;
  onPress?: () => void;
  variant?: Variant;
  size?: Size;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
  fullWidth?: boolean;
}

const DARK_LABEL = "#08101F";

const labelColors: Record<Variant, string> = {
  primary: DARK_LABEL,
  danger: DARK_LABEL,
  buy: DARK_LABEL,
  sell: "#FFFFFF",
  secondary: colors.accent,
  ghost: colors.accent,
};

export function Button({
  label,
  onPress,
  variant = "primary",
  size = "md",
  disabled,
  loading,
  style,
  fullWidth,
}: Props) {
  const isDisabled = disabled || loading;

  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.base,
        size === "sm" ? styles.sm : styles.md,
        variantStyles[variant],
        fullWidth && { alignSelf: "stretch" },
        isDisabled && { opacity: 0.5 },
        pressed && !isDisabled && { opacity: 0.85 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={labelColors[variant]} size="small" />
      ) : (
        <Text variant="bodyStrong" style={{ color: labelColors[variant] }}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
  },
  md: { paddingVertical: spacing.md, paddingHorizontal: spacing.xl },
  sm: { paddingVertical: spacing.sm, paddingHorizontal: spacing.lg },
});

const variantStyles: Record<Variant, ViewStyle> = {
  primary: { backgroundColor: colors.accent },
  secondary: { backgroundColor: "transparent", borderWidth: 1, borderColor: colors.accent },
  danger: { backgroundColor: colors.negative },
  ghost: { backgroundColor: "transparent" },
  buy: { backgroundColor: colors.positive },
  sell: { backgroundColor: colors.negative },
};
