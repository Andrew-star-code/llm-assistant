import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { scenarioKeys } from "@/features/scenarios/api";
import { ScenarioIcon } from "@/features/scenarios/icons";

/** Админка «Сценарии» (§13.2): список; правка и тестовый чат — в редакторе. */
export function ScenarioListPage() {
  const { t } = useTranslation();
  const scenarios = useQuery({
    queryKey: scenarioKeys.admin,
    queryFn: async () => unwrap(await api.GET("/api/admin/scenarios")),
  });
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{t("admin.nav.scenarios")}</h1>
        <Link
          to="/admin/scenarios/new"
          className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="size-4" /> {t("admin.scenarios.new")}
        </Link>
      </div>
      <Table
        head={[
          t("admin.scenarios.name"),
          t("admin.scenarios.roles"),
          t("admin.scenarios.model"),
          t("admin.scenarios.ragMode"),
          t("admin.scenarios.status"),
        ]}
      >
        {(scenarios.data ?? []).map((s) => (
          <tr key={s.id} data-testid="scenario-row">
            <Td>
              <Link
                to={`/admin/scenarios/${s.id}`}
                className="flex items-center gap-2 font-medium hover:underline"
              >
                <ScenarioIcon name={s.icon ?? null} className="size-4 text-primary" />
                {s.name}
              </Link>
              <div className="text-xs text-muted-foreground">{s.code}</div>
            </Td>
            <Td>{s.roles?.length ? s.roles.join(", ") : t("admin.scenarios.everyone")}</Td>
            <Td>{s.model_role}</Td>
            <Td>{t(`admin.scenarios.ragModes.${s.rag_mode}`)}</Td>
            <Td>
              {s.is_active ? (
                <Badge tone="ok">{t("admin.scenarios.active")}</Badge>
              ) : (
                <Badge tone="muted">{t("admin.scenarios.inactive")}</Badge>
              )}
            </Td>
          </tr>
        ))}
      </Table>
    </section>
  );
}
