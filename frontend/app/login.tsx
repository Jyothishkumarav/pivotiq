import React, { useState } from "react";
import {
  Modal,
  Platform,
  Pressable,
  TouchableOpacity,
  View,
} from "react-native";
import { useRouter } from "expo-router";
import { Button, Card, Input, Screen, Text } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { colors, radius, shadows, spacing } from "@/theme/tokens";

export default function LoginScreen() {
  const login = useAuthStore((s) => s.login);
  const router = useRouter();

  // Modal & Form state
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Register link prompt state
  const [showRegisterNotice, setShowRegisterNotice] = useState(false);

  const handlePivotIQLogin = async () => {
    if (!username.trim() || !password) {
      setError("Please enter your username and password");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await login(username.trim(), password);
      setIsModalVisible(false);
      router.replace("/(tabs)/search");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  const openModal = () => {
    setError(null);
    setShowRegisterNotice(false);
    setIsModalVisible(true);
  };

  const closeModal = () => {
    setIsModalVisible(false);
    setError(null);
    setShowRegisterNotice(false);
  };

  return (
    <Screen scroll={false} width="narrow">
      <View style={{ flex: 1, justifyContent: "center", gap: spacing.xxl }}>
        {/* Brand Header */}
        <View style={{ alignItems: "center", gap: spacing.md }}>
          <View
            style={{
              width: 64,
              height: 64,
              borderRadius: 20,
              backgroundColor: colors.accentMuted,
              borderWidth: 1.5,
              borderColor: colors.accent,
              alignItems: "center",
              justifyContent: "center",
              ...shadows.card,
            }}
          >
            <Text variant="display" tone="accent" style={{ fontSize: 34, fontWeight: "800" }}>
              P
            </Text>
          </View>
          <Text variant="display" style={{ letterSpacing: -0.8 }}>PivotIQ</Text>
          <Text variant="body" tone="secondary" style={{ textAlign: "center", maxWidth: 360 }}>
            Precision intraday breakouts, VWAP confirmations, and automated algorithmic tracking.
          </Text>
        </View>

        {/* Main Card */}
        <Card elevated style={{ gap: spacing.lg, padding: spacing.xl }}>
          <View style={{ gap: spacing.xs }}>
            <Text variant="title">Sign in</Text>
            <Text variant="caption" tone="secondary">
              Choose your authentication method to access the terminal.
            </Text>
          </View>

          {/* Primary Login Button */}
          <Button
            label="Continue as PivotIQ User"
            variant="primary"
            fullWidth
            onPress={openModal}
          />

          {/* Google Login Placeholder */}
          <Button label="Continue with Google" variant="secondary" fullWidth disabled />

          {error && !isModalVisible ? (
            <Text variant="caption" tone="negative" style={{ textAlign: "center" }}>
              {error}
            </Text>
          ) : null}

          {/* Register Link */}
          <TouchableOpacity
            onPress={openModal}
            activeOpacity={0.7}
            style={{ alignItems: "center", marginTop: spacing.xs }}
          >
            <Text variant="caption" tone="secondary">
              Don't have an account?{" "}
              <Text variant="caption" tone="accent" style={{ fontWeight: "700" }}>
                Register
              </Text>
            </Text>
          </TouchableOpacity>
        </Card>

        {/* Footer */}
        <Text variant="caption" tone="muted" style={{ textAlign: "center" }}>
          Market data & paper trading platform. Not investment advice.
        </Text>
      </View>

      {/* Login Popup Modal */}
      <Modal
        visible={isModalVisible}
        transparent
        animationType="fade"
        onRequestClose={closeModal}
      >
        <Pressable
          style={{
            flex: 1,
            backgroundColor: "rgba(4, 7, 15, 0.82)",
            justifyContent: "center",
            alignItems: "center",
            padding: spacing.lg,
            ...(Platform.OS === "web" ? ({ backdropFilter: "blur(8px)" } as any) : {}),
          }}
          onPress={closeModal}
        >
          {/* Prevent clicks on card from closing modal */}
          <Pressable
            style={{
              width: "100%",
              maxWidth: 420,
              backgroundColor: colors.surface,
              borderRadius: radius.xl,
              borderWidth: 1,
              borderColor: colors.border,
              padding: spacing.xl,
              gap: spacing.lg,
              ...shadows.card,
            }}
            onPress={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <View style={{ gap: spacing.xs, flex: 1 }}>
                <Text variant="title">PivotIQ Sign In</Text>
                <Text variant="caption" tone="secondary">
                  Enter your credentials to access your trading suite.
                </Text>
              </View>
              <TouchableOpacity
                onPress={closeModal}
                style={{
                  padding: spacing.xs,
                  borderRadius: radius.sm,
                  backgroundColor: colors.surfaceElevated,
                }}
              >
                <Text variant="caption" tone="secondary" style={{ paddingHorizontal: spacing.xs }}>
                  ✕
                </Text>
              </TouchableOpacity>
            </View>

            {/* Error Banner */}
            {error ? (
              <View
                style={{
                  backgroundColor: colors.negativeBg,
                  borderRadius: radius.md,
                  borderWidth: 1,
                  borderColor: colors.negative,
                  padding: spacing.sm,
                }}
              >
                <Text variant="caption" tone="negative" style={{ textAlign: "center" }}>
                  {error}
                </Text>
              </View>
            ) : null}

            {/* Register Notice */}
            {showRegisterNotice ? (
              <View
                style={{
                  backgroundColor: colors.accentMuted,
                  borderRadius: radius.md,
                  borderWidth: 1,
                  borderColor: colors.accent,
                  padding: spacing.md,
                  gap: spacing.xs,
                }}
              >
                <Text variant="caption" tone="accent" style={{ fontWeight: "700" }}>
                  Registration Notice
                </Text>
                <Text variant="caption" tone="secondary">
                  Account registration is currently invite-only. If you do not have an account, please contact your administrator for access credentials.
                </Text>
              </View>
            ) : null}

            {/* Credentials Form */}
            <View style={{ gap: spacing.md }}>
              <Input
                label="Username or Email"
                placeholder="e.g. jyo_admin"
                value={username}
                onChangeText={setUsername}
                autoCapitalize="none"
                autoCorrect={false}
                returnKeyType="next"
              />

              <Input
                label="Password"
                placeholder="Enter password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry={!showPassword}
                autoCapitalize="none"
                autoCorrect={false}
                returnKeyType="done"
                onSubmitEditing={handlePivotIQLogin}
                rightElement={
                  <TouchableOpacity
                    onPress={() => setShowPassword(!showPassword)}
                    style={{ paddingHorizontal: spacing.xs }}
                    activeOpacity={0.7}
                  >
                    <Text variant="caption" tone="accent" style={{ fontWeight: "600" }}>
                      {showPassword ? "Hide" : "Show"}
                    </Text>
                  </TouchableOpacity>
                }
              />
            </View>

            {/* Submit Button */}
            <Button
              label="Sign In"
              variant="primary"
              onPress={handlePivotIQLogin}
              loading={loading}
              fullWidth
            />

            {/* Modal Footer / Register Link */}
            <View style={{ alignItems: "center", gap: spacing.xs, paddingTop: spacing.xs }}>
              <TouchableOpacity
                onPress={() => setShowRegisterNotice(true)}
                activeOpacity={0.7}
              >
                <Text variant="caption" tone="secondary">
                  Don't have an account?{" "}
                  <Text variant="caption" tone="accent" style={{ fontWeight: "700" }}>
                    Register
                  </Text>
                </Text>
              </TouchableOpacity>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </Screen>
  );
}
