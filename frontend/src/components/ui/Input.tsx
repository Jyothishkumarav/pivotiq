import React from "react";
import { TextInput, TextInputProps, View } from "react-native";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { Text } from "./Text";

interface Props extends TextInputProps {
  label?: string;
}

export function Input({ label, style, ...rest }: Props) {
  return (
    <View style={{ gap: spacing.xs }}>
      {label ? (
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
      ) : null}
      <TextInput
        placeholderTextColor={colors.textMuted}
        style={[
          {
            backgroundColor: colors.surfaceElevated,
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            color: colors.textPrimary,
            ...typography.body,
          },
          style,
        ]}
        {...rest}
      />
    </View>
  );
}
