import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import type { Me } from "@/features/auth/useMe";
import { useThemeStore, type ThemeMode } from "@/features/theme/store";

/**
 * Тема хранится и в localStorage (чтобы не мигала при загрузке), и в настройках пользователя
 * на сервере (§7.10): после входа применяется серверная тема, последующие смены сохраняются.
 */
export function ThemeServerSync({ me }: { me: Me }) {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  const serverTheme = me.settings.theme ?? null;
  const lastSaved = useRef<ThemeMode | null | undefined>(undefined);

  useEffect(() => {
    if (lastSaved.current === undefined) {
      // Первый рендер после входа: серверная тема важнее локальной.
      lastSaved.current = serverTheme ?? mode;
      if (serverTheme && serverTheme !== mode) setMode(serverTheme);
      return;
    }
    if (lastSaved.current === mode) return;
    lastSaved.current = mode;
    void api.PATCH("/api/profile/settings", { body: { theme: mode } });
  }, [mode, serverTheme, setMode]);

  return null;
}
