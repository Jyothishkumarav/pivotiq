import React from "react";
import { TextInput, TextInputProps, View } from "react-native";
import { colors, radius, spacing, typography } from "@/theme/tokens";
import { Text } from "./Text";

interface Props extends TextInputProps {
  label?: string;
  rightElement?: React.ReactNode;
}

export function Input({ label, rightElement, style, ...rest }: Props) {
  return (
    <View style={{ gap: spacing.xs }}>
      {label ? (
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
      ) : null}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          backgroundColor: colors.surfaceElevated,
          borderWidth: 1,
          borderColor: colors.border,
          borderRadius: radius.md,
          paddingHorizontal: spacing.md,
        }}
      >
        <TextInput
          placeholderTextColor={colors.textMuted}
          style={[
            {
              flex: 1,
              paddingVertical: spacing.md,
              color: colors.textPrimary,
              ...typography.body,
            },
            style,
          ]}
          {...rest}
        />
        {rightElement}
      </View>
    </View>
  );
}
