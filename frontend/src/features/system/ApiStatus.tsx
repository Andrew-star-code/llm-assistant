import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { cn } from "@/lib/utils";

type Status = "loading" | "ready" | "degraded" | "down";

async function fetchReadiness(): Promise<Status> {
  const { data, response } = await api.GET("/ready");
  if (data) return "ready";
  // 503 приходит с телом ReadinessResponse — api жив, но зависимость недоступна.
  return response.status === 503 ? "degraded" : "down";
}

/** Индикатор готовности api в шапке — проверка сквозного пути SPA → прокси → api на этапе 0. */
export function ApiStatus() {
  const { t } = useTranslation();
  const { data, isPending, isError } = useQuery({
    queryKey: ["system", "ready"],
    queryFn: fetchReadiness,
    refetchInterval: 30_000,
  });
  const status: Status = isPending ? "loading" : isError ? "down" : data;

  return (
    <span
      className="flex items-center gap-2 text-xs text-muted-foreground"
      data-testid="api-status"
      data-status={status}
    >
      <span
        className={cn(
          "size-2 rounded-full",
          status === "ready" && "bg-emerald-500",
          status === "degraded" && "bg-amber-500",
          status === "down" && "bg-red-500",
          status === "loading" && "bg-muted-foreground/40",
        )}
        aria-hidden
      />
      {t(`apiStatus.${status}`)}
    </span>
  );
}
