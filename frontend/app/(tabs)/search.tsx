import React, { useEffect, useState } from "react";
import { Platform, Pressable, useWindowDimensions, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Card, Input, Screen, Text } from "@/components/ui";
import { stocksApi } from "@/api/stocks";
import { colors, layout, spacing } from "@/theme/tokens";

export default function SearchScreen() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const { width } = useWindowDimensions();
  const twoColumn = Platform.OS === "web" && width >= layout.wideBreakpoint;

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const { data: results, isFetching } = useQuery({
    queryKey: ["stock-search", debounced],
    queryFn: () => stocksApi.search(debounced),
    enabled: debounced.trim().length > 0,
  });

  return (
    <Screen width="wide">
      <View style={{ gap: spacing.xs }}>
        <Text variant="display">Search stocks</Text>
        <Text variant="body" tone="secondary">
          NSE-listed equities. Type a symbol or company name.
        </Text>
      </View>

      <Card>
        <Input
          placeholder="e.g. RELIANCE, TCS, or Infosys"
          value={query}
          onChangeText={setQuery}
          autoCapitalize="characters"
          autoFocus={Platform.OS === "web"}
        />
      </Card>

      {isFetching ? (
        <Text variant="caption" tone="muted">
          Searching…
        </Text>
      ) : null}

      <View
        style={{
          flexDirection: twoColumn ? "row" : "column",
          flexWrap: "wrap",
          gap: spacing.md,
        }}
      >
        {(results ?? []).map((s) => (
          <Pressable
            key={s.symbol}
            onPress={() => router.push(`/stock/${s.symbol}`)}
            style={{ flexBasis: twoColumn ? "48.5%" : "100%", flexGrow: 1 }}
          >
            {({ hovered }: any) => (
              <Card
                style={{
                  gap: spacing.xs,
                  borderColor: hovered ? colors.border : colors.borderSubtle,
                  backgroundColor: hovered ? colors.surfaceElevated : colors.surface,
                }}
              >
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text variant="subtitle">{s.symbol}</Text>
                  <Text variant="caption" tone="muted">
                    {s.exchange}
                  </Text>
                </View>
                <Text variant="body" tone="secondary" numberOfLines={1}>
                  {s.name}
                </Text>
              </Card>
            )}
          </Pressable>
        ))}
        {debounced.trim().length > 0 && !isFetching && (results?.length ?? 0) === 0 ? (
          <Text variant="body" tone="muted">
            No matching stocks found.
          </Text>
        ) : null}
        {debounced.trim().length === 0 && !isFetching ? (
          <Text variant="body" tone="muted">
            Start typing to see suggestions.
          </Text>
        ) : null}
      </View>
    </Screen>
  );
}
