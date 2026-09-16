import React from "react";
import { ActivityIndicator, View, ViewStyle } from "react-native";
import { colors, spacing } from "@/theme/tokens";
import { Text } from "./Text";

interface Props {
  label?: string;
  compact?: boolean;
  style?: ViewStyle;
}

export function LoadingBlock({ label = "Loading…", compact = false, style }: Props) {
  return (
    <View
      style={[
        {
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: spacing.md,
          paddingVertical: compact ? spacing.md : spacing.xxl,
        },
        style,
      ]}
    >
      <ActivityIndicator color={colors.accent} size={compact ? "small" : "small"} />
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
    </View>
  );
}
