import React from "react";
import { Platform } from "react-native";
import { Slot, Tabs } from "expo-router";
import { Text } from "@/components/ui";
import { colors } from "@/theme/tokens";

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

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.textPrimary,
        headerShadowVisible: false,
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
