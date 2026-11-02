import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";

import { api, ApiError, unwrap, type Schemas } from "@/api/client";

export type MyLimits = Schemas["LimitsOut"];
export type LimitItem = Schemas["LimitItem"];
export const LIMITS_QUERY_KEY = ["limits"] as const;

/** Остатки по лимитам пользователя (§12.4); обновляются событием SSE `limits` в конце ответа. */
export function useMyLimits() {
  return useQuery({
    queryKey: LIMITS_QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/limits")),
    // Окна сбрасываются по часам — раз в минуту поле ввода узнаёт, что лимит обновился.
    refetchInterval: 60_000,
  });
}

/** Части даты по часам компании: «обновится в 00:00» совпадает с текстом сервера (§12.1). */
function parts(date: Date, timeZone: string | undefined) {
  const format = new Intl.DateTimeFormat("ru-RU", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const get = (type: string) => format.formatToParts(date).find((p) => p.type === type)?.value;
  return {
    day: `${get("year") ?? ""}-${get("month") ?? ""}-${get("day") ?? ""}`,
    date: `${get("day") ?? ""}.${get("month") ?? ""}`,
    time: `${get("hour") ?? ""}:${get("minute") ?? ""}`,
  };
}

/** «в 00:00» — сегодня или в ближайшую полночь; дальше — «09.11 в 00:00». */
export function resetWhen(t: TFunction, resetAt: string, timeZone?: string): string {
  const at = parts(new Date(resetAt), timeZone);
  const today = parts(new Date(), timeZone).day;
  const tomorrow = parts(new Date(Date.now() + 86_400_000), timeZone).day;
  const nextMidnight = at.day === tomorrow && at.time === "00:00";
  return at.day === today || nextMidnight
    ? t("limits.at", { time: at.time })
    : t("limits.onDate", { date: at.date, time: at.time });
}

const compact = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });

/** Число в метрике: токены — «1,2 млн», остальное как есть. */
export function amount(metric: string, value: number): string {
  return metric === "tokens" ? compact.format(value) : value.toLocaleString("ru-RU");
}

export interface LimitDetails {
  metric: string;
  window: string | null;
  model_role?: string | null;
  thinking?: boolean;
  limit: number;
  used?: number;
  reset_at: string | null;
  timezone?: string;
}

/** Понятный текст исчерпанного лимита (§12.4) — и для 429, и для заблокированного поля ввода. */
export function exhaustedText(t: TFunction, d: LimitDetails, timeZone?: string): string {
  if (d.metric === "concurrent_generations") {
    return t("limits.concurrent", { limit: d.limit });
  }
  const what = [
    t(`limits.genitive.${d.metric}`, { defaultValue: d.metric }),
    d.thinking ? t("limits.thinkingSuffix") : "",
    d.model_role ? t("limits.modelSuffix", { role: d.model_role }) : "",
  ]
    .filter(Boolean)
    .join(" ");
  const head = t("limits.exhausted", {
    window: t(`limits.windowAdj.${d.window ?? "none"}`),
    what,
  });
  const when = d.reset_at
    ? t("limits.resets", { when: resetWhen(t, d.reset_at, d.timezone ?? timeZone) })
    : "";
  return `${head}${when}. ${t("limits.askAdmin")}`;
}

/** Текст ошибки для пользователя: превышение лимита — из i18n по `details`, остальное как есть. */
export function errorText(t: TFunction, error: Error): string {
  if (error instanceof ApiError && error.code === "limit_exceeded" && error.details) {
    return exhaustedText(t, error.details as unknown as LimitDetails);
  }
  return error.message;
}

/** Причина блокировки поля ввода: исчерпанный лимит, действующий на все сообщения (§12.4). */
export function blockingItem(limits: MyLimits | undefined): LimitItem | null {
  if (!limits?.blocked) return null;
  return (
    limits.items.find(
      (i) =>
        (i.metric === "messages" || i.metric === "tokens") &&
        !i.model_role &&
        !i.thinking &&
        i.remaining <= 0,
    ) ?? null
  );
}
