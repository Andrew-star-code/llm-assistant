import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeStore, type ThemeMode } from "@/features/theme/store";
import { cn } from "@/lib/utils";

const OPTIONS: { mode: ThemeMode; icon: LucideIcon }[] = [
  { mode: "light", icon: Sun },
  { mode: "dark", icon: Moon },
  { mode: "system", icon: Monitor },
];

/** Переключатель «Светлая / Тёмная / Как в системе» (§7.10). */
export function ThemeToggle() {
  const { t } = useTranslation();
  const { mode, setMode } = useThemeStore();
  return (
    <div
      role="radiogroup"
      aria-label={t("theme.label")}
      className="inline-flex rounded-md border border-border p-0.5"
    >
      {OPTIONS.map(({ mode: option, icon: Icon }) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={mode === option}
          aria-label={t(`theme.${option}`)}
          title={t(`theme.${option}`)}
          data-testid={`theme-${option}`}
          onClick={() => {
            setMode(option);
          }}
          className={cn(
            "rounded-sm p-1.5 text-muted-foreground transition-colors hover:text-foreground",
            mode === option && "bg-muted text-foreground",
          )}
        >
          <Icon className="size-4" />
        </button>
      ))}
    </div>
  );
}
