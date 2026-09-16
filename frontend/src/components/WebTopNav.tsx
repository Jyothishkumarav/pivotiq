import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Text } from "@/components/ui";
import { settingsApi, type DataSourceMode } from "@/api/settings";
import { colors, layout, radius, spacing } from "@/theme/tokens";

interface NavItem {
  href: "/(tabs)/search" | "/(tabs)/watchlists" | "/(tabs)/alerts" | "/(tabs)/portfolio";
  label: string;
  key: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/(tabs)/search", label: "Search", key: "search" },
  { href: "/(tabs)/watchlists", label: "Watchlists", key: "watchlists" },
  { href: "/(tabs)/alerts", label: "Alerts", key: "alerts" },
  { href: "/(tabs)/portfolio", label: "Portfolio", key: "portfolio" },
];

function DataSourceToggle() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["settings", "data-source"],
    queryFn: settingsApi.getDataSource,
  });

  const mutation = useMutation({
    mutationFn: (mode: DataSourceMode) => settingsApi.setDataSource(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "data-source"] });
      queryClient.invalidateQueries({ queryKey: ["quote"] });
      queryClient.invalidateQueries({ queryKey: ["fundamentals"] });
      queryClient.invalidateQueries({ queryKey: ["support-levels"] });
      queryClient.invalidateQueries({ queryKey: ["stock-search"] });
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
    },
  });

  const mode = data?.mode ?? "real";
  const isReal = mode === "real";
  const dotColor = isReal ? colors.positive : colors.warning;
  const label = isReal ? "Live · Yahoo" : "Demo · Mock";
  const nextLabel = isReal ? "Switch to demo" : "Switch to live";

  return (
    <Pressable
      onPress={() => mutation.mutate(isReal ? "mock" : "real")}
      disabled={mutation.isPending}
      style={({ hovered }: any) => [
        styles.dataSource,
        hovered && { backgroundColor: colors.surfaceElevated, borderColor: colors.border },
      ]}
    >
      <View style={{ width: 8, height: 8, borderRadius: 999, backgroundColor: dotColor }} />
      <Text variant="caption" tone="secondary">
        {mutation.isPending ? "Switching…" : label}
      </Text>
      <Text variant="caption" tone="muted">
        · {nextLabel}
      </Text>
    </Pressable>
  );
}

export function WebTopNav() {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <View style={styles.navOuter}>
      <View style={styles.navInner}>
        <Pressable
          onPress={() => router.push("/(tabs)/search")}
          style={styles.brandRow}
        >
          <View style={styles.brandDot} />
          <Text variant="title" style={{ letterSpacing: -0.4 }}>
            PivotIQ
          </Text>
        </Pressable>
        <View style={styles.navLinks}>
          {NAV_ITEMS.map((item) => {
            const active = pathname === `/${item.key}` || pathname.startsWith(`/${item.key}/`);
            return (
              <Pressable
                key={item.key}
                onPress={() => router.push(item.href)}
                style={({ hovered }: any) => [
                  styles.navLink,
                  active && styles.navLinkActive,
                  hovered && !active && styles.navLinkHovered,
                ]}
              >
                <Text
                  variant="bodyStrong"
                  style={{ color: active ? colors.textPrimary : colors.textSecondary }}
                >
                  {item.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <DataSourceToggle />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  navOuter: {
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.background,
    position: "sticky" as any,
    top: 0,
    zIndex: 100,
  },
  navInner: {
    height: layout.navHeight,
    maxWidth: layout.contentMaxWidth,
    width: "100%",
    alignSelf: "center",
    paddingHorizontal: spacing.xxl,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.xxl,
  },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  brandDot: {
    width: 12,
    height: 12,
    borderRadius: 999,
    backgroundColor: colors.accent,
  },
  navLinks: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  navLink: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: 8,
  },
  navLinkHovered: { backgroundColor: colors.surface },
  navLinkActive: { backgroundColor: colors.surfaceElevated },
  dataSource: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surface,
  },
});
