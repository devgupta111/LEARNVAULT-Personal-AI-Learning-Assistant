/**
 * hooks/useTheme.ts
 *
 * Theme management hook — Light / Dark / Green themes.
 *
 * - Reads/writes theme to localStorage under key "app-theme".
 * - Applies a CSS data attribute (`data-theme`) on <html> so CSS variables
 *   can target each theme without any runtime JS after initial paint.
 * - On first load, falls back to the OS dark-mode preference for a smooth default.
 * - SSR-safe: all localStorage access is gated behind `typeof window !== "undefined"`.
 */

"use client";

import { useEffect, useState, useCallback } from "react";

export type Theme = "light" | "dark" | "green";

const STORAGE_KEY = "app-theme";

/** Derive the initial theme without triggering a React render cycle. */
function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
  if (saved === "light" || saved === "dark" || saved === "green") return saved;
  // Fall back to OS preference
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  if (typeof window === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  // Also set/remove `dark` class for Tailwind dark-mode utilities
  if (theme === "dark" || theme === "green") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("dark");

  // On mount, read from localStorage and apply
  useEffect(() => {
    const initial = getInitialTheme();
    setThemeState(initial);
    applyTheme(initial);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, next);
    }
  }, []);

  return { theme, setTheme };
}
