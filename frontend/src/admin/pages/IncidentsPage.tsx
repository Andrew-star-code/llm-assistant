import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { formatDateTime } from "@/lib/format";

const TONE = { low: "muted", warning: "warn", high: "bad", critical: "bad" } as const;

/** Инциденты (§13.5) — минимум этапа 4: список; карточка и работа с инцидентом — этап 7. */
export function IncidentsPage() {
  const { t } = useTranslation();
  const incidents = useQuery({
    queryKey: ["admin", "incidents"],
    queryFn: async () => unwrap(await api.GET("/api/admin/incidents")),
    refetchInterval: 30_000,
  });
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.incidents")}</h1>
      <Table
        head={[
          t("admin.incidents.lastSeen"),
          t("admin.incidents.severity"),
          t("admin.incidents.title"),
          t("admin.incidents.occurrences"),
          t("admin.incidents.status"),
        ]}
      >
        {(incidents.data?.items ?? []).map((i) => (
          <tr key={i.id} data-testid="incident-row">
            <Td>{formatDateTime(i.last_seen)}</Td>
            <Td>
              <Badge tone={i.severity in TONE ? TONE[i.severity as keyof typeof TONE] : "muted"}>
                {i.severity}
              </Badge>
            </Td>
            <Td>
              <div>{i.title}</div>
              <div className="text-xs text-muted-foreground">{i.type}</div>
            </Td>
            <Td>{i.occurrences}</Td>
            <Td>{t(`admin.incidents.statuses.${i.status}`, { defaultValue: i.status })}</Td>
          </tr>
        ))}
      </Table>
      {incidents.data?.items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.incidents.empty")}</p>
      )}
    </section>
  );
}
