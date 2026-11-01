import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { formatDateTime } from "@/lib/format";

/** «Инструменты» (§13.2): включение и выключение, статистика вызовов за 30 дней. */
export function ToolsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const tools = useQuery({
    queryKey: ["admin", "tools"],
    queryFn: async () => unwrap(await api.GET("/api/admin/tools")),
  });
  const toggle = useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) =>
      unwrap(
        await api.PUT("/api/admin/tools/{name}", {
          params: { path: { name } },
          body: { enabled },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "tools"] });
    },
  });
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.tools")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.tools.hint")}</p>
      <Table
        head={[
          t("admin.tools.enabled"),
          t("admin.tools.name"),
          t("admin.tools.calls"),
          t("admin.tools.errors"),
          t("admin.tools.avg"),
          t("admin.tools.lastUsed"),
        ]}
      >
        {(tools.data ?? []).map((tool) => (
          <tr key={tool.name} data-testid="tool-row">
            <Td>
              <input
                type="checkbox"
                aria-label={`${t("admin.tools.enabled")}: ${tool.name}`}
                checked={tool.enabled}
                disabled={!tool.in_config || toggle.isPending}
                onChange={(e) => {
                  toggle.mutate({ name: tool.name, enabled: e.target.checked });
                }}
              />
            </Td>
            <Td className="max-w-md">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-medium">{tool.name}</code>
                {tool.visibility === "hidden" && (
                  <Badge tone="warn">{t("admin.tools.hidden")}</Badge>
                )}
                {!tool.in_config && <Badge tone="muted">{t("admin.tools.inConfig")}</Badge>}
              </div>
              <div className="line-clamp-2 text-xs text-muted-foreground">{tool.description}</div>
              {tool.required_permissions.length > 0 && (
                <div className="text-xs text-muted-foreground">
                  {t("admin.tools.permissions", { list: tool.required_permissions.join(", ") })}
                </div>
              )}
            </Td>
            <Td className="tabular-nums">{tool.calls}</Td>
            <Td className="tabular-nums">{tool.errors}</Td>
            <Td className="tabular-nums">
              {tool.avg_duration_ms !== null
                ? t("admin.dashboard.ms", { value: tool.avg_duration_ms })
                : "—"}
            </Td>
            <Td className="whitespace-nowrap">{formatDateTime(tool.last_used_at)}</Td>
          </tr>
        ))}
      </Table>
    </section>
  );
}
