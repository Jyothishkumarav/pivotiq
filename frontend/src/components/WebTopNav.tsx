import React from "react";
import { Platform, Pressable, StyleSheet, View } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Text } from "@/components/ui";
import { fyersApi } from "@/api/fyers";
import { useAuthStore } from "@/store/authStore";
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
  const { data } = useQuery({
    queryKey: ["fyers", "status"],
    queryFn: fyersApi.status,
    refetchInterval: 60_000,
  });

  const connected = data?.connected ?? false;
  const dotColor = connected ? colors.positive : colors.negative;
  const label = connected ? "Live · Fyers connected" : "Live API not connected";

  return (
    <View style={styles.dataSource}>
      <View style={{ width: 8, height: 8, borderRadius: 999, backgroundColor: dotColor }} />
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
    </View>
  );
}

function UserMenu() {
  const { user, status, logout } = useAuthStore();
  const router = useRouter();

  if (status !== "authenticated" || !user) {
    return (
      <Pressable
        onPress={() => router.push("/login")}
        style={({ hovered }: any) => [
          styles.signInBtn,
          hovered && { backgroundColor: colors.accentHover },
        ]}
      >
        <Text variant="caption" style={{ color: "#fff", fontWeight: "700" }}>
          Sign In
        </Text>
      </Pressable>
    );
  }

  const initial = (user.name || user.email || "U").charAt(0).toUpperCase();
  const displayName = user.name || user.email.split("@")[0];

  const handleLogout = async () => {
    await logout();
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.location.replace("/login");
    } else {
      router.replace("/login");
    }
  };

  return (
    <View style={styles.userSection}>
      {/* User Badge / Icon */}
      <View style={styles.userBadge}>
        <View style={styles.avatar}>
          <Text variant="caption" style={{ color: "#fff", fontWeight: "800", fontSize: 11 }}>
            {initial}
          </Text>
        </View>
        <Text
          variant="caption"
          style={{ color: colors.textPrimary, fontWeight: "600", maxWidth: 100 }}
          numberOfLines={1}
        >
          {displayName}
        </Text>
      </View>

      {/* Logout Action */}
      <Pressable
        onPress={handleLogout}
        style={({ hovered }: any) => [
          styles.logoutBtn,
          hovered && styles.logoutBtnHovered,
        ]}
      >
        <Text variant="caption" tone="negative" style={{ fontWeight: "700" }}>
          Log out
        </Text>
      </Pressable>
    </View>
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
        <View style={styles.rightActions}>
          <DataSourceToggle />
          <UserMenu />
        </View>
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
    gap: spacing.lg,
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
  rightActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
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
  userSection: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  userBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingLeft: 4,
    paddingRight: spacing.md,
    paddingVertical: 3,
    borderRadius: radius.full,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  avatar: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  logoutBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.full,
    backgroundColor: colors.negativeBg,
    borderWidth: 1,
    borderColor: "rgba(255, 107, 133, 0.3)",
  },
  logoutBtnHovered: {
    backgroundColor: "rgba(255, 107, 133, 0.25)",
    borderColor: colors.negative,
  },
  signInBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    borderRadius: radius.full,
    backgroundColor: colors.accent,
  },
});
