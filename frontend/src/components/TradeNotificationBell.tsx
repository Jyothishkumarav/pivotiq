import React, { useMemo, useState } from "react";
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Card, Text } from "@/components/ui";
import { tradingApi } from "@/api/trading";
import { TradeNotification } from "@/types";
import { colors, radius, spacing } from "@/theme/tokens";
import { formatCurrency } from "@/utils/format";

export function formatTimeIST(isoString: string): string {
  try {
    const d = new Date(
      isoString.endsWith("Z") || isoString.includes("+") ? isoString : isoString + "Z"
    );
    return d.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      timeZone: "Asia/Kolkata",
    });
  } catch {
    return isoString;
  }
}

export function openFyersWeb(symbol: string) {
  const fyersSym = `NSE:${symbol.toUpperCase()}-EQ`;
  const url = `https://fyers.in/web/symbol/${fyersSym}`;
  if (Platform.OS === "web" && typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

export function TradeNotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  // Poll notifications every 3 seconds for fast responsiveness
  const { data: notifications = [] } = useQuery<TradeNotification[]>({
    queryKey: ["trade-notifications"],
    queryFn: tradingApi.getTradeNotifications,
    refetchInterval: 3000,
  });

  const markReadMutation = useMutation({
    mutationFn: tradingApi.markNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trade-notifications"] });
    },
  });

  // Calculate unread count
  const unreadCount = useMemo(() => {
    return notifications.filter((n) => !n.read).length;
  }, [notifications]);

  const handleCopy = (item: TradeNotification) => {
    const text = `${item.side.toUpperCase()} ${item.qty} ${item.symbol} @ ₹${item.entryPrice.toFixed(2)} | SL ₹${item.stopLoss.toFixed(2)}`;
    if (Platform.OS === "web" && typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      if (typeof window !== "undefined") {
        window.alert(`Copied to clipboard:\n${text}`);
      }
    }
  };

  return (
    <View style={{ position: "relative", zIndex: 1000 }}>
      {/* Bell Button Trigger in Nav Bar */}
      <Pressable
        onPress={() => setOpen((prev) => !prev)}
        style={({ hovered }: any) => [
          styles.bellBtn,
          hovered && styles.bellBtnHovered,
          open && styles.bellBtnActive,
        ]}
        accessibilityLabel="Trade alerts & Fyers notifications"
      >
        <Text style={{ fontSize: 16, lineHeight: 20 }}>🔔</Text>
        {unreadCount > 0 ? (
          <View style={styles.unreadBadge}>
            <Text style={styles.unreadText}>
              {unreadCount > 9 ? "9+" : unreadCount}
            </Text>
          </View>
        ) : null}
      </Pressable>

      {/* Notifications Dropdown Drawer */}
      {open ? (
        <>
          {Platform.OS === "web" && (
            <Pressable
              onPress={() => setOpen(false)}
              style={styles.backdrop}
            />
          )}
          <View style={styles.drawer}>
            <View style={styles.drawerHeader}>
              <View style={{ flex: 1, gap: 3, paddingRight: spacing.sm, minWidth: 0 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, flexWrap: "wrap" }}>
                  <Text variant="subtitle" style={{ fontSize: 14, fontWeight: "700", color: colors.textPrimary }}>
                    Trade Alerts & Fyers Orders
                  </Text>
                  {unreadCount > 0 ? (
                    <Badge label={`${unreadCount} new`} tone="positive" />
                  ) : null}
                </View>
                <Text variant="caption" tone="muted" numberOfLines={1}>
                  Click link to place order immediately on Fyers Web
                </Text>
              </View>

              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, flexShrink: 0 }}>
                {unreadCount > 0 ? (
                  <Pressable
                    onPress={() => markReadMutation.mutate()}
                    style={({ hovered }: any) => [
                      styles.markReadBtn,
                      hovered && { backgroundColor: colors.surfaceHover },
                    ]}
                  >
                    <Text variant="caption" tone="accent" style={{ fontSize: 11, fontWeight: "600" }}>
                      Mark read
                    </Text>
                  </Pressable>
                ) : null}
                <Pressable
                  onPress={() => setOpen(false)}
                  style={({ hovered }: any) => [
                    styles.closeBtn,
                    hovered && { backgroundColor: colors.surfaceHover },
                  ]}
                  accessibilityLabel="Close notifications"
                >
                  <Text variant="caption" tone="muted" style={{ fontSize: 14, fontWeight: "700" }}>✕</Text>
                </Pressable>
              </View>
            </View>

            {/* List of Notifications */}
            <ScrollView
              style={{ maxHeight: 420 }}
              contentContainerStyle={{ padding: spacing.sm, paddingBottom: spacing.lg, gap: spacing.sm }}
            >
              {notifications.length === 0 ? (
                <View style={{ paddingVertical: spacing.xl, alignItems: "center", gap: spacing.xs }}>
                  <Text style={{ fontSize: 24 }}>📭</Text>
                  <Text variant="caption" tone="muted">
                    No trade alerts triggered today yet
                  </Text>
                </View>
              ) : (
                notifications.map((item) => {
                  const isBuy = item.side.toLowerCase() === "buy";
                  return (
                    <Card key={item.id} style={styles.notifCard}>
                      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.xs }}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, flex: 1, minWidth: 0, flexWrap: "wrap" }}>
                          <Badge
                            label={isBuy ? "BUY" : "SELL"}
                            tone={isBuy ? "positive" : "negative"}
                          />
                          <Text variant="subtitle" style={{ fontSize: 14, fontWeight: "700" }}>
                            {item.symbol}
                          </Text>
                          <Text variant="caption" tone="muted" style={{ fontSize: 11 }}>
                            NSE:{item.symbol}-EQ
                          </Text>
                        </View>
                        <Text variant="caption" tone="muted" style={{ fontSize: 11, flexShrink: 0 }}>
                          {formatTimeIST(item.time)}
                        </Text>
                      </View>

                      {/* Trade Metrics */}
                      <View style={styles.metricsRow}>
                        <View style={styles.metricBox}>
                          <Text variant="caption" tone="muted" style={{ fontSize: 10 }}>QTY</Text>
                          <Text variant="mono" style={{ fontSize: 13, fontWeight: "700" }}>{item.qty}</Text>
                        </View>
                        <View style={styles.metricBox}>
                          <Text variant="caption" tone="muted" style={{ fontSize: 10 }}>ENTRY</Text>
                          <Text variant="mono" style={{ fontSize: 13, fontWeight: "700" }}>{formatCurrency(item.entryPrice)}</Text>
                        </View>
                        <View style={styles.metricBox}>
                          <Text variant="caption" tone="muted" style={{ fontSize: 10 }}>STOP LOSS</Text>
                          <Text variant="mono" tone="warning" style={{ fontSize: 13, fontWeight: "700" }}>{formatCurrency(item.stopLoss)}</Text>
                        </View>
                      </View>

                      {/* Action Links */}
                      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, marginTop: 4 }}>
                        <Pressable
                          onPress={() => openFyersWeb(item.symbol)}
                          style={({ hovered }: any) => [
                            styles.cardFyersBtn,
                            hovered && { backgroundColor: "#2563EB" },
                          ]}
                        >
                          <Text variant="caption" style={{ color: "#fff", fontWeight: "700", fontSize: 11 }}>
                            Open in Fyers (NSE:{item.symbol}-EQ) ↗
                          </Text>
                        </Pressable>
                        <Pressable
                          onPress={() => handleCopy(item)}
                          style={({ hovered }: any) => [
                            styles.cardCopyBtn,
                            hovered && { backgroundColor: colors.surfaceHover },
                          ]}
                        >
                          <Text variant="caption" tone="secondary" style={{ fontSize: 11, fontWeight: "600" }}>
                            Copy
                          </Text>
                        </Pressable>
                      </View>
                    </Card>
                  );
                })
              )}
            </ScrollView>
          </View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bellBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
  },
  bellBtnHovered: {
    backgroundColor: colors.surfaceHover,
    borderColor: colors.accent,
  },
  bellBtnActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
  },
  unreadBadge: {
    position: "absolute",
    top: -3,
    right: -3,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.negative,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 3,
    borderWidth: 1.5,
    borderColor: colors.background,
  },
  unreadText: {
    color: "#fff",
    fontSize: 9,
    fontWeight: "800",
    lineHeight: 11,
  },
  backdrop: {
    position: "fixed" as any,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 9998,
  },
  drawer: {
    position: "absolute",
    top: 44,
    right: 0,
    width: 440,
    maxWidth: "94vw" as any,
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    zIndex: 9999,
    ...(Platform.OS === "web" ? ({ boxShadow: "0 14px 34px rgba(0, 0, 0, 0.55)" } as any) : {}),
    elevation: 10,
    overflow: "hidden",
  },
  drawerHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSubtle,
    gap: spacing.xs,
  },
  markReadBtn: {
    paddingHorizontal: spacing.xs + 4,
    paddingVertical: 4,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  closeBtn: {
    width: 28,
    height: 28,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.sm,
  },
  notifCard: {
    backgroundColor: colors.surface,
    borderColor: colors.borderSubtle,
    borderWidth: 1,
    padding: spacing.sm,
    gap: spacing.xs,
  },
  metricsRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.sm,
    paddingVertical: 5,
    paddingHorizontal: spacing.sm,
    justifyContent: "space-between",
  },
  metricBox: {
    gap: 1,
  },
  cardFyersBtn: {
    flex: 1,
    backgroundColor: "#1A56DB",
    paddingVertical: 6,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  cardCopyBtn: {
    paddingVertical: 6,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    alignItems: "center",
  },
});
