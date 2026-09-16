import React, { useState } from "react";
import { View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, Screen, Text } from "@/components/ui";
import { alertsApi } from "@/api/alerts";
import { spacing } from "@/theme/tokens";
import { AlertChannel, ThresholdType } from "@/types";
import { formatCurrency } from "@/utils/format";

export default function NewAlertScreen() {
  const params = useLocalSearchParams<{ symbol: string; method: string; levelKey: string; levelValue: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [thresholdType, setThresholdType] = useState<ThresholdType>("percent");
  const [thresholdValue, setThresholdValue] = useState("2");
  const [channels, setChannels] = useState<AlertChannel[]>(["push"]);

  const createMutation = useMutation({
    mutationFn: () =>
      alertsApi.create({
        symbol: params.symbol,
        method: params.method,
        levelKey: params.levelKey,
        thresholdType,
        thresholdValue: Number(thresholdValue),
        channels,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      router.back();
    },
  });

  const toggleChannel = (channel: AlertChannel) => {
    setChannels((prev) => (prev.includes(channel) ? prev.filter((c) => c !== channel) : [...prev, channel]));
  };

  return (
    <Screen scroll={false} width="narrow">
      <Text variant="display">New alert</Text>

      <Card style={{ gap: spacing.sm }}>
        <Text variant="subtitle">{params.symbol}</Text>
        <Text variant="body" tone="secondary">
          {params.method} · {params.levelKey.toUpperCase()}
        </Text>
        <Text variant="mono">{formatCurrency(Number(params.levelValue))}</Text>
      </Card>

      <Card style={{ gap: spacing.md }}>
        <Text variant="subtitle">Threshold type</Text>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <Button
            label="% away"
            size="sm"
            variant={thresholdType === "percent" ? "primary" : "secondary"}
            onPress={() => setThresholdType("percent")}
          />
          <Button
            label="₹ away"
            size="sm"
            variant={thresholdType === "absolute" ? "primary" : "secondary"}
            onPress={() => setThresholdType("absolute")}
          />
        </View>
        <Input
          label={thresholdType === "percent" ? "Notify within (%)" : "Notify within (₹)"}
          keyboardType="numeric"
          value={thresholdValue}
          onChangeText={setThresholdValue}
        />
      </Card>

      <Card style={{ gap: spacing.md }}>
        <Text variant="subtitle">Channels</Text>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <Button
            label="Push"
            size="sm"
            variant={channels.includes("push") ? "primary" : "secondary"}
            onPress={() => toggleChannel("push")}
          />
          <Button
            label="Email"
            size="sm"
            variant={channels.includes("email") ? "primary" : "secondary"}
            onPress={() => toggleChannel("email")}
          />
        </View>
      </Card>

      <Button
        label="Save alert"
        onPress={() => createMutation.mutate()}
        loading={createMutation.isPending}
        disabled={!thresholdValue || channels.length === 0}
        fullWidth
      />
      {createMutation.isError ? (
        <Text variant="caption" tone="negative">
          {(createMutation.error as Error).message}
        </Text>
      ) : null}
    </Screen>
  );
}
