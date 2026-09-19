import React from "react";
import { Pressable, StyleSheet, View, ViewStyle } from "react-native";
import { colors, radius, spacing } from "@/theme/tokens";
import { Text } from "./Text";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  tone?: "positive" | "negative" | "default";
}

interface Props<T extends string> {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  style?: ViewStyle;
}

export function Segmented<T extends string>({ value, options, onChange, style }: Props<T>) {
  return (
    <View style={[styles.container, style]}>
      {options.map((opt) => {
        const active = opt.value === value;
        const activeBg =
          opt.tone === "positive"
            ? colors.positiveBg
            : opt.tone === "negative"
              ? colors.negativeBg
              : colors.surfaceElevated;
        const activeBorder =
          opt.tone === "positive"
            ? colors.positive
            : opt.tone === "negative"
              ? colors.negative
              : colors.accent;
        const activeText =
          opt.tone === "positive"
            ? colors.positiveText
            : opt.tone === "negative"
              ? colors.negative
              : colors.textPrimary;

        return (
          <Pressable
            key={opt.value}
            onPress={() => onChange(opt.value)}
            style={[
              styles.item,
              {
                backgroundColor: active ? activeBg : "transparent",
                borderColor: active ? activeBorder : "transparent",
              },
            ]}
          >
            <Text
              variant="bodyStrong"
              style={{ color: active ? activeText : colors.textSecondary, textAlign: "center" }}
            >
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    backgroundColor: colors.background,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 4,
    gap: 4,
  },
  item: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
  },
});
