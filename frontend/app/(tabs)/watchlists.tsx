import React, { useState } from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, LoadingBlock, Screen, Text } from "@/components/ui";
import { watchlistsApi } from "@/api/watchlists";
import { colors, layout, radius, spacing } from "@/theme/tokens";

function DeleteWatchlistButton({ onPress, disabled }: { onPress: () => void; disabled: boolean }) {
  return (
    <Pressable
      onPress={(e: any) => {
        e?.stopPropagation?.();
        onPress();
      }}
      disabled={disabled}
      hitSlop={8}
      style={({ hovered }: any) => ({
        width: 30,
        height: 30,
        borderRadius: radius.full,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: hovered ? colors.negativeBg : "transparent",
        borderWidth: 1,
        borderColor: hovered ? colors.negative : colors.borderSubtle,
        opacity: disabled ? 0.4 : 1,
      })}
    >
      <Text
        variant="bodyStrong"
        style={{ color: colors.textSecondary, lineHeight: 18, fontSize: 16 }}
      >
        ×
      </Text>
    </Pressable>
  );
}

export default function WatchlistsScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const { width } = useWindowDimensions();
  const twoColumn = Platform.OS === "web" && width >= layout.wideBreakpoint;

  const { data: watchlists, isLoading, isFetching } = useQuery({
    queryKey: ["watchlists"],
    queryFn: watchlistsApi.list,
    refetchInterval: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => watchlistsApi.create(name),
    onSuccess: () => {
      setNewName("");
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => watchlistsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watchlists"] }),
  });

  return (
    <Screen width="wide">
      <View style={{ gap: spacing.xs }}>
        <Text variant="display">Your watchlists</Text>
        <Text variant="body" tone="secondary">
          Group stocks by theme. Sort by proximity to support to spot buying opportunities.
        </Text>
        <Text variant="caption" tone="muted">
          Prices auto-refresh every 30s
          {isFetching && !isLoading ? " · refreshing…" : ""}
        </Text>
      </View>

      <Card style={{ gap: spacing.md }}>
        <Text variant="subtitle">Create a watchlist</Text>
        <View style={{ flexDirection: twoColumn ? "row" : "column", gap: spacing.md, alignItems: twoColumn ? "flex-end" : "stretch" }}>
          <View style={{ flex: 1 }}>
            <Input placeholder="e.g. IT stocks, Long-term bets" value={newName} onChangeText={setNewName} />
          </View>
          <Button
            label="Create"
            onPress={() => newName.trim() && createMutation.mutate(newName.trim())}
            loading={createMutation.isPending}
            disabled={!newName.trim()}
          />
        </View>
      </Card>

      {isLoading ? <LoadingBlock label="Loading watchlists…" compact /> : null}

      <View
        style={{
          flexDirection: twoColumn ? "row" : "column",
          flexWrap: "wrap",
          gap: spacing.md,
        }}
      >
        {(watchlists ?? []).map((wl) => {
          const isDeleting = deleteMutation.isPending && deleteMutation.variables === wl.id;
          return (
            <Pressable
              key={wl.id}
              onPress={() => router.push(`/watchlist/${wl.id}`)}
              style={{ flexBasis: twoColumn ? "48.5%" : "100%", flexGrow: 1 }}
            >
              {({ hovered }: any) => (
                <Card
                  style={{
                    flexDirection: "row",
                    justifyContent: "space-between",
                    alignItems: "center",
                    borderColor: hovered ? colors.border : colors.borderSubtle,
                    backgroundColor: hovered ? colors.surfaceElevated : colors.surface,
                    opacity: isDeleting ? 0.5 : 1,
                  }}
                >
                  <View style={{ gap: spacing.xs, flex: 1 }}>
                    <Text variant="subtitle">{wl.name}</Text>
                    <Text variant="caption" tone="secondary">
                      {wl.items.length} stock{wl.items.length === 1 ? "" : "s"} · sorted by {wl.sortPreference}
                    </Text>
                  </View>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md }}>
                    <Text variant="title" tone="muted">
                      ›
                    </Text>
                    <DeleteWatchlistButton
                      onPress={() => deleteMutation.mutate(wl.id)}
                      disabled={isDeleting}
                    />
                  </View>
                </Card>
              )}
            </Pressable>
          );
        })}
        {!isLoading && (watchlists?.length ?? 0) === 0 ? (
          <Text variant="body" tone="muted">
            No watchlists yet — create your first one above.
          </Text>
        ) : null}
      </View>
    </Screen>
  );
}
