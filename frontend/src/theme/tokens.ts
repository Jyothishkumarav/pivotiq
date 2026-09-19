import { Platform } from "react-native";

export const colors = {
  background: "#0A0F1C",
  surface: "#111827",
  surfaceElevated: "#1A2236",
  surfaceHover: "#212C46",
  border: "#293449",
  borderSubtle: "#1E2740",
  divider: "#1B2337",

  textPrimary: "#F1F5FB",
  textSecondary: "#A1AAC0",
  textMuted: "#6B7590",

  accent: "#5B8BFF",
  accentHover: "#7CA1FF",
  accentMuted: "#1F2C4E",

  positive: "#3DDB9F",
  positiveText: "#3DDB9F",
  positiveBg: "#0F2C24",
  negative: "#FF6B85",
  negativeBg: "#341421",
  warning: "#F5B54A",
  warningBg: "#3A2A0C",

  overlay: "rgba(6, 10, 20, 0.6)",
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
};

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  full: 999,
};

export const typography = {
  display: { fontSize: 28, fontWeight: "700" as const, letterSpacing: -0.5, lineHeight: 34 },
  title: { fontSize: 20, fontWeight: "700" as const, letterSpacing: -0.3, lineHeight: 26 },
  subtitle: { fontSize: 16, fontWeight: "600" as const, lineHeight: 22 },
  body: { fontSize: 14, fontWeight: "400" as const, lineHeight: 20 },
  bodyStrong: { fontSize: 14, fontWeight: "600" as const, lineHeight: 20 },
  caption: { fontSize: 12, fontWeight: "500" as const, lineHeight: 16 },
  mono: {
    fontSize: 14,
    fontWeight: "600" as const,
    lineHeight: 20,
    fontVariant: ["tabular-nums"] as const,
  },
};

export const layout = {
  contentMaxWidth: 1240,
  narrowMaxWidth: 720,
  navHeight: 64,
  wideBreakpoint: 900,
};

export const shadows = {
  card:
    Platform.OS === "web"
      ? ({ boxShadow: "0 1px 2px rgba(0,0,0,0.25), 0 4px 12px rgba(0,0,0,0.18)" } as any)
      : {
          shadowColor: "#000",
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.18,
          shadowRadius: 12,
          elevation: 4,
        },
};
