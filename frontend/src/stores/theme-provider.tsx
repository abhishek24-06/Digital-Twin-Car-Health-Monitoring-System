"use client";

import * as React from "react";

/**
 * Theme: dark-first with a coherent light theme, driven by the same design
 * tokens (so charts, forms, dialogs and tables all follow automatically).
 *
 * localStorage + the `<html>` class are the source of truth, so this is
 * modelled as an external store via `useSyncExternalStore`. The inline script in
 * the root layout applies the stored theme before paint; this provider keeps
 * React in step with later changes, including other tabs.
 */

export type Theme = "dark" | "light";

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeState | null>(null);

export const THEME_STORAGE_KEY = "dt-theme";
const THEME_EVENT = "dt-theme-change";

function normalize(value: string | null): Theme {
  return value === "light" ? "light" : "dark";
}

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return normalize(window.localStorage.getItem(THEME_STORAGE_KEY));
}

function getServerSnapshot(): Theme {
  return "dark";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** Writes the theme to the document and localStorage, then notifies React. */
function writeTheme(next: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("light", next === "light");
  root.classList.toggle("dark", next === "dark");
  root.style.colorScheme = next;
  window.localStorage.setItem(THEME_STORAGE_KEY, next);
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = React.useSyncExternalStore(
    subscribe,
    readStoredTheme,
    getServerSnapshot,
  );

  const setTheme = React.useCallback((next: Theme) => {
    writeTheme(next);
  }, []);

  const toggleTheme = React.useCallback(() => {
    writeTheme(readStoredTheme() === "dark" ? "light" : "dark");
  }, []);

  const value = React.useMemo(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const context = React.useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return context;
}

/** Inline script injected before hydration to prevent theme flash. */
export const themeInitScript = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');var l=t==='light';document.documentElement.classList.toggle('light',l);document.documentElement.classList.toggle('dark',!l);document.documentElement.style.colorScheme=l?'light':'dark';}catch(e){}})();`;
