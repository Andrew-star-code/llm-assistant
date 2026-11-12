import { useEffect } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";

/** Ключ localStorage; тот же читает public/theme-init.js до загрузки React. */
export const THEME_STORAGE_KEY = "ai-assistant.theme";

interface ThemeState {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

// Выбор хранится в localStorage, чтобы тема не мигала при загрузке (§7.10); с настройками
// пользователя на сервере его сверяет ThemeServerSync.
export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: "system",
      setMode: (mode) => {
        set({ mode });
      },
    }),
    { name: THEME_STORAGE_KEY, storage: createJSONStorage(() => localStorage), version: 1 },
  ),
);

export function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveDark(mode: ThemeMode, systemDark: boolean): boolean {
  return mode === "dark" || (mode === "system" && systemDark);
}

export function applyTheme(mode: ThemeMode): void {
  const dark = resolveDark(mode, prefersDark());
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

/** Применяет тему и следит за системной, если выбран режим «Как в системе». */
export function useThemeEffect(): void {
  const mode = useThemeStore((s) => s.mode);
  useEffect(() => {
    applyTheme(mode);
    if (mode !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      applyTheme("system");
    };
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, [mode]);
}
