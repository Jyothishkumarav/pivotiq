import React from "react";
import { Platform, TouchableOpacity, View } from "react-native";
import { Slot, Tabs, useRouter } from "expo-router";
import { Text } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { colors, radius, spacing } from "@/theme/tokens";

const NATIVE_TABS = [
  { key: "search", label: "Search", icon: "🔍" },
  { key: "watchlists", label: "Watchlists", icon: "⭐" },
  { key: "alerts", label: "Alerts", icon: "🔔" },
  { key: "portfolio", label: "Portfolio", icon: "💼" },
];

export default function TabsLayout() {
  if (Platform.OS === "web") {
    return <Slot />;
  }

  const { user, logout } = useAuthStore();
  const router = useRouter();
  const initial = (user?.name || user?.email || "U").charAt(0).toUpperCase();

  const handleLogout = async () => {
    await logout();
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.location.replace("/login");
    } else {
      router.replace("/login");
    }
  };

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.textPrimary,
        headerShadowVisible: false,
        headerRight: () => (
          <TouchableOpacity
            onPress={handleLogout}
            style={{
              marginRight: spacing.lg,
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.xs,
              paddingHorizontal: spacing.sm,
              paddingVertical: 4,
              borderRadius: radius.full,
              backgroundColor: colors.surface,
              borderWidth: 1,
              borderColor: colors.borderSubtle,
            }}
          >
            <View
              style={{
                width: 22,
                height: 22,
                borderRadius: 11,
                backgroundColor: colors.accent,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Text variant="caption" style={{ color: "#fff", fontWeight: "700", fontSize: 10 }}>
                {initial}
              </Text>
            </View>
            <Text variant="caption" tone="negative" style={{ fontWeight: "700" }}>
              Log out
            </Text>
          </TouchableOpacity>
        ),
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.borderSubtle,
          height: 64,
          paddingTop: 6,
          paddingBottom: 8,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
      }}
    >
      {NATIVE_TABS.map((item) => (
        <Tabs.Screen
          key={item.key}
          name={item.key}
          options={{
            title: item.label,
            tabBarIcon: ({ focused }) => (
              <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{item.icon}</Text>
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
