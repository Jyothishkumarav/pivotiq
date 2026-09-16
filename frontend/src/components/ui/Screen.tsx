import React from "react";
import {
  Platform,
  ScrollView,
  ScrollViewProps,
  StyleSheet,
  useWindowDimensions,
  View,
  ViewProps,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, layout, spacing } from "@/theme/tokens";

interface Props extends ViewProps {
  scroll?: boolean;
  width?: "wide" | "narrow";
  contentContainerStyle?: ScrollViewProps["contentContainerStyle"];
}

export function Screen({
  scroll = true,
  width = "wide",
  style,
  contentContainerStyle,
  children,
  ...rest
}: Props) {
  const { width: windowWidth } = useWindowDimensions();
  const isWeb = Platform.OS === "web";
  const isDesktop = isWeb && windowWidth >= layout.wideBreakpoint;

  const maxWidth = width === "narrow" ? layout.narrowMaxWidth : layout.contentMaxWidth;

  const containerStyle = {
    padding: isDesktop ? spacing.xxl : spacing.lg,
    paddingBottom: spacing.xxxl,
    gap: spacing.lg,
    maxWidth,
    width: "100%" as const,
    alignSelf: "center" as const,
  };

  const inner = scroll ? (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[styles.center, contentContainerStyle]}
      showsVerticalScrollIndicator={false}
    >
      <View style={containerStyle}>{children}</View>
    </ScrollView>
  ) : (
    <View style={[styles.center, { flex: 1 }]}>
      <View style={[containerStyle, { flex: 1 }, style]} {...rest}>
        {children}
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {inner}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { flex: 1 },
  center: { alignItems: "center", flexGrow: 1 },
});
