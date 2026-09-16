import React from "react";
import { View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, LoadingBlock, Screen, Text } from "@/components/ui";
import { alertsApi } from "@/api/alerts";
import { spacing } from "@/theme/tokens";
import { formatCurrency, formatPercent } from "@/utils/format";

export default function AlertsScreen() {
  const queryClient = useQueryClient();
  const { data: alerts, isLoading } = useQuery({ queryKey: ["alerts"], queryFn: alertsApi.list });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) => alertsApi.update(id, { isActive }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => alertsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  return (
    <Screen width="wide">
      <View style={{ gap: spacing.xs }}>
        <Text variant="display">Alerts</Text>
        <Text variant="body" tone="secondary">
          All alerts across your watchlists. Create new ones from a stock detail screen.
        </Text>
      </View>

      {isLoading ? <LoadingBlock label="Loading alerts…" compact /> : null}

      <View style={{ gap: spacing.sm }}>
        {(alerts ?? []).map((a) => (
          <Card key={a.id} style={{ gap: spacing.sm }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text variant="subtitle">{a.symbol}</Text>
              <Badge label={a.isActive ? "Active" : "Muted"} tone={a.isActive ? "positive" : "neutral"} />
            </View>
            <Text variant="caption" tone="secondary">
              {a.method} · {a.levelKey.toUpperCase()} @ {formatCurrency(a.levelValueAtCreation)}
            </Text>
            <Text variant="caption" tone="secondary">
              Notify within {a.thresholdType === "percent" ? `${a.thresholdValue}%` : formatCurrency(a.thresholdValue)}
              {" · "}
              {a.channels.join(", ")}
            </Text>
            {a.currentDistancePercent !== null ? (
              <Text variant="caption" tone="muted">
                Currently {formatPercent(a.currentDistancePercent)} from level
              </Text>
            ) : null}
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Button
                label={a.isActive ? "Mute" : "Re-arm"}
                size="sm"
                variant="secondary"
                onPress={() => toggleMutation.mutate({ id: a.id, isActive: !a.isActive })}
              />
              <Button label="Delete" size="sm" variant="danger" onPress={() => deleteMutation.mutate(a.id)} />
            </View>
          </Card>
        ))}
        {!isLoading && (alerts?.length ?? 0) === 0 ? (
          <Text variant="body" tone="muted">
            No alerts yet.
          </Text>
        ) : null}
      </View>
    </Screen>
  );
}
