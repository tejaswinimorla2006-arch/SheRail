export const THEME_TOKENS = {
  light: {
    background: "#f7f4f6",
    surface: "#ffffff",
    surfaceMuted: "#f2edf0",
    text: "#241a20",
    muted: "#766b72",
    border: "#e9e1e5",
    accent: "#a83f64",
    accentForeground: "#ffffff",
    accentSoft: "#f8eaf0",
    journey: "#fff0f4",
    sos: "#b4232d",
    sosForeground: "#ffffff",
    sosSoft: "#fff0f1",
    header: "#ffffff",
  },
  dark: {
    background: "#111217",
    surface: "#1b1d24",
    surfaceMuted: "#252730",
    text: "#f7f2f4",
    muted: "#b7adb3",
    border: "#34323b",
    accent: "#f0a2ba",
    accentForeground: "#24141a",
    accentSoft: "#382630",
    journey: "#2b2028",
    sos: "#ff777e",
    sosForeground: "#2b0d12",
    sosSoft: "#3a2226",
    header: "#191a20",
  },
};

export function getThemeTokens(colorScheme) {
  return colorScheme === "dark" ? THEME_TOKENS.dark : THEME_TOKENS.light;
}
