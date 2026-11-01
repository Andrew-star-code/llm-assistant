import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type ModelInfo = Schemas["ModelInfo"];

function Visibility({ model }: { model: ModelInfo }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(model.visible_to.join(", "));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/admin/models/{role}/visibility", {
          params: { path: { role: model.role } },
          body: {
            roles: value
              .split(",")
              .map((r) => r.trim())
              .filter(Boolean),
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
    },
  });
  if (!model.restrictable) {
    return <span className="text-xs text-muted-foreground">{t("admin.models.locked")}</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-1">
        <Input
          aria-label={`${t("admin.models.visibleTo")}: ${model.role}`}
          placeholder={t("admin.models.rolesPlaceholder")}
          className="h-8 w-48"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          {t("admin.models.save")}
        </Button>
      </div>
      <span className="text-xs text-muted-foreground">
        {model.visible_to.length ? model.visible_to.join(", ") : t("admin.models.everyone")}
      </span>
      {save.isError && (
        <span role="alert" className="text-xs text-red-600">
          {save.error instanceof ApiError ? save.error.message : t("common.loadError")}
        </span>
      )}
    </div>
  );
}

/** «Модели» (§13.2): реестр по ролям, состояние эндпоинтов, видимость по ролям. */
export function ModelsPage() {
  const { t } = useTranslation();
  const models = useQuery({
    queryKey: ["admin", "models"],
    queryFn: async () => unwrap(await api.GET("/api/admin/models")),
  });
  const health = useQuery({
    queryKey: ["admin", "models-health"],
    queryFn: async () => unwrap(await api.GET("/api/admin/models/health")),
  });
  const status = new Map((health.data ?? []).map((h) => [h.role, h]));
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{t("admin.nav.models")}</h1>
        <Button
          variant="outline"
          size="sm"
          disabled={health.isFetching}
          onClick={() => {
            void health.refetch();
          }}
        >
          {t("admin.models.check")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{t("admin.models.hint")}</p>
      <Table
        head={[
          t("admin.models.role"),
          t("admin.models.model"),
          t("admin.models.status"),
          t("admin.models.visibleTo"),
          t("admin.models.scenarios"),
        ]}
      >
        {(models.data ?? []).map((m) => {
          const h = status.get(m.role);
          return (
            <tr key={m.role} data-testid="model-row">
              <Td className="font-medium">{m.role}</Td>
              <Td>
                <div>{m.model}</div>
                <div className="text-xs text-muted-foreground">
                  {m.base_url}
                  {m.context_length
                    ? ` · ${t("admin.models.context")} ${String(m.context_length)}`
                    : ""}
                  {m.supports_tools ? ` · ${t("admin.models.toolsSupport")}` : ""}
                  {m.thinking_mode !== "none"
                    ? ` · ${t("admin.models.thinking")}: ${m.thinking_mode}`
                    : ""}
                </div>
              </Td>
              <Td>
                {h ? (
                  <Badge tone={h.ok ? "ok" : "bad"}>
                    {h.ok
                      ? `${t("admin.models.ok")}${h.latency_ms !== null ? ` · ${t("admin.dashboard.ms", { value: h.latency_ms })}` : ""}`
                      : `${t("admin.models.down")}${h.detail ? ` · ${h.detail}` : ""}`}
                  </Badge>
                ) : (
                  "…"
                )}
              </Td>
              <Td>
                <Visibility key={m.visible_to.join(",")} model={m} />
              </Td>
              <Td className="text-xs">{m.scenarios.join(", ") || "—"}</Td>
            </tr>
          );
        })}
      </Table>
    </section>
  );
}
