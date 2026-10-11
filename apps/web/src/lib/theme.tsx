"use client";

import { useCallback, useLayoutEffect, useState } from "react";
import { resolveTheme, type Theme } from "./theme-resolve";

export type { Theme };
export { resolveTheme };
export const THEME_KEY = "edb_theme";

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStored(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(THEME_KEY);
}

function currentTheme(): Theme {
  return resolveTheme(readStored(), systemPrefersDark());
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

/** Inline bootstrap script so the first paint already has the right theme. */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_KEY,
)});if(t!=="dark"&&t!=="light"){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.setAttribute("data-theme",t)}catch(e){}})();`;

/**
 * Theme hook. Locale navigations remount the [locale] layout (and this hook);
 * client navigations do not re-run THEME_BOOT_SCRIPT, so we must re-apply the
 * stored theme on every mount via useLayoutEffect — independently of locale.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(currentTheme);

  useLayoutEffect(() => {
    const initial = currentTheme();
    setThemeState(initial);
    applyTheme(initial);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (!readStored()) {
        const next = resolveTheme(null, mq.matches);
        setThemeState(next);
        applyTheme(next);
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggle };
}
