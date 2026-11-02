import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { amount, resetWhen, useMyLimits, type LimitItem } from "@/features/limits/api";
import { cn } from "@/lib/utils";

function label(t: ReturnType<typeof useTranslation>["t"], item: LimitItem): string {
  const parts = [t(`limits.metric.${item.metric}`, { defaultValue: item.metric })];
  if (item.window) parts.push(t(`limits.window.${item.window}`));
  if (item.thinking) parts.push(t("limits.thinkingOnly"));
  if (item.model_role) parts.push(t("limits.modelOnly", { role: item.model_role }));
  return parts.join(" · ");
}

/** Полная картина лимитов в профиле (§12.4): полосы по всем метрикам и время сброса. */
export function LimitsSection() {
  const { t } = useTranslation();
  const limits = useMyLimits();
  const items = limits.data?.items ?? [];
  const { hash } = useLocation();
  const ref = useRef<HTMLElement>(null);
  // «Лимиты» из меню пользователя ведут на /profile#limits — прокрутить, когда данные пришли.
  useEffect(() => {
    if (hash === "#limits" && items.length) ref.current?.scrollIntoView({ block: "start" });
  }, [hash, items.length]);
  return (
    <section id="limits" ref={ref} data-testid="profile-limits">
      <h2 className="mb-1 font-semibold">{t("limits.title")}</h2>
      <p className="mb-3 text-sm text-muted-foreground">{t("limits.hint")}</p>
      <ul className="flex flex-col gap-3">
        {items.map((item) => {
          const percent = item.limit > 0 ? Math.min(100, (item.used / item.limit) * 100) : 100;
          return (
            <li
              key={`${item.metric}-${item.window ?? ""}-${item.model_role ?? ""}-${String(item.thinking)}`}
              className="flex flex-col gap-1"
              data-testid={`limit-${item.metric}`}
            >
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span>{label(t, item)}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {t("limits.usage", {
                    used: amount(item.metric, item.used),
                    limit: amount(item.metric, item.limit),
                  })}
                  {item.reset_at &&
                    ` · ${t("limits.resetAt", { when: resetWhen(t, item.reset_at, limits.data?.timezone) })}`}
                </span>
              </div>
              <div
                className="h-2 overflow-hidden rounded-full bg-muted"
                role="progressbar"
                aria-label={label(t, item)}
                aria-valuemin={0}
                aria-valuemax={item.limit}
                aria-valuenow={Math.min(item.used, item.limit)}
              >
                <div
                  className={cn(
                    "h-full",
                    percent >= 100 ? "bg-red-600" : percent >= 90 ? "bg-amber-500" : "bg-primary",
                  )}
                  style={{ width: `${String(percent)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
