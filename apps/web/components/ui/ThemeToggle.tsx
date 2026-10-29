"use client";

import { useTheme } from "../theme/ThemeProvider";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const nextTheme = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
  const label = theme === "system" ? "System theme" : `${theme[0].toUpperCase()}${theme.slice(1)} theme`;

  return (
    <button
      className="icon-button"
      type="button"
      aria-label={`${label}. Switch to ${nextTheme} theme`}
      title={`Theme: ${label}`}
      onClick={() => setTheme(nextTheme)}
    >
      {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
    </button>
  );
}
