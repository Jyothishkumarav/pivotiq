import React from "react";
import { View, ViewProps, ViewStyle } from "react-native";
import { colors, radius, shadows, spacing } from "@/theme/tokens";

interface Props extends ViewProps {
  padded?: boolean;
  elevated?: boolean;
  style?: ViewStyle | ViewStyle[];
}

export function Card({ padded = true, elevated = false, style, children, ...rest }: Props) {
  return (
    <View
      style={[
        {
          backgroundColor: elevated ? colors.surfaceElevated : colors.surface,
          borderRadius: radius.lg,
          borderWidth: 1,
          borderColor: colors.borderSubtle,
          padding: padded ? spacing.xl : 0,
        },
        shadows.card,
        style,
      ]}
      {...rest}
    >
      {children}
    </View>
  );
}
