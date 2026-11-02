import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import { Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { amount, resetWhen } from "@/features/limits/api";
import { formatDateTime } from "@/lib/format";

type Metric = Schemas["PolicyIn"]["metric"];
const RAISABLE: { metric: Metric; window: "day" | null }[] = [
  { metric: "messages", window: "day" },
  { metric: "tokens", window: "day" },
  { metric: "uploads", window: "day" },
  { metric: "concurrent_generations", window: null },
  { metric: "personal_kb_storage", window: null },
  { metric: "personal_kb_documents", window: null },
];
const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";

/** Карточка пользователя (§13.2): эффективные лимиты, откуда они, сброс и временное повышение. */
export function UserLimits({ userId }: { userId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["admin", "user-limits", userId];
  const [metric, setMetric] = useState<Metric>("messages");
  const [value, setValue] = useState("");
  const [days, setDays] = useState("7");
  const limits = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/users/{user_id}/limits", {
          params: { path: { user_id: userId } },
        }),
      ),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const reset = useMutation({
    mutationFn: async () => {
      unwrap(
        await api.POST("/api/admin/users/{user_id}/limits/reset", {
          params: { path: { user_id: userId } },
          body: { metric: null },
        }),
      );
    },
    onSuccess: () => refresh(),
  });
  const raise = useMutation({
    mutationFn: async () => {
      const spec = RAISABLE.find((r) => r.metric === metric) ?? RAISABLE[0];
      const expires = new Date(Date.now() + Number(days) * 86_400_000);
      return unwrap(
        await api.POST("/api/admin/limits/policies", {
          body: {
            scope: "user",
            target_id: userId,
            metric,
            window: spec?.window ?? null,
            limit: Number(value),
            thinking: false,
            expires_at: expires.toISOString(),
            note: t("admin.limits.raiseNote", { days }),
          },
        }),
      );
    },
    onSuccess: () => {
      setValue("");
      void refresh();
      void queryClient.invalidateQueries({ queryKey: ["admin", "limit-policies"] });
    },
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    raise.mutate();
  };
  const error = reset.error ?? raise.error;

  return (
    <section data-testid="user-limits">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-semibold">{t("limits.title")}</h2>
        <Button
          size="sm"
          variant="outline"
          disabled={reset.isPending}
          onClick={() => {
            reset.mutate();
          }}
        >
          {t("admin.limits.reset")}
        </Button>
      </div>
      <Table
        head={[
          t("admin.limits.key"),
          t("admin.limits.usage"),
          t("admin.limits.source"),
          t("admin.limits.resetsAt"),
        ]}
      >
        {(limits.data?.items ?? []).map((l) => (
          <tr
            key={`${l.metric}-${l.window ?? ""}-${l.model_role ?? ""}-${String(l.thinking)}`}
            data-testid="user-limit-row"
          >
            <Td>
              {[
                t(`limits.metric.${l.metric}`, { defaultValue: l.metric }),
                l.window ? t(`limits.window.${l.window}`) : null,
                l.thinking ? t("limits.thinkingOnly") : null,
                l.model_role ? t("limits.modelOnly", { role: l.model_role }) : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </Td>
            <Td className="tabular-nums">
              {t("limits.usage", {
                used: amount(l.metric, l.used),
                limit: amount(l.metric, l.limit),
              })}
            </Td>
            <Td className="text-xs">
              {t(`admin.limits.sources.${l.source}`, { name: l.source_name ?? "" })}
              {l.expires_at &&
                ` · ${t("admin.limits.until", { date: formatDateTime(l.expires_at) })}`}
            </Td>
            <Td className="text-xs">
              {l.reset_at ? resetWhen(t, l.reset_at, limits.data?.timezone) : "—"}
            </Td>
          </tr>
        ))}
      </Table>
      <form
        onSubmit={submit}
        className="mt-3 flex flex-wrap items-center gap-2 text-sm"
        data-testid="raise-limit-form"
      >
        <span>{t("admin.limits.raise")}</span>
        <select
          aria-label={t("admin.limits.metric")}
          className={SELECT}
          value={metric}
          onChange={(e) => {
            setMetric(e.target.value as Metric);
          }}
        >
          {RAISABLE.map((r) => (
            <option key={r.metric} value={r.metric}>
              {t(`limits.metric.${r.metric}`)}
              {r.window ? ` · ${t(`limits.window.${r.window}`)}` : ""}
            </option>
          ))}
        </select>
        <Input
          required
          type="number"
          min={0}
          className="w-36"
          aria-label={t("admin.limits.limit")}
          placeholder={t("admin.limits.limit")}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
        />
        <label className="flex items-center gap-1.5">
          {t("admin.limits.forDays")}
          <Input
            required
            type="number"
            min={1}
            max={365}
            className="w-20"
            aria-label={t("admin.limits.days")}
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
            }}
          />
        </label>
        <Button type="submit" size="sm" disabled={raise.isPending}>
          {t("admin.limits.raiseButton")}
        </Button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error instanceof ApiError ? error.message : t("common.loadError")}
        </p>
      )}
    </section>
  );
}
