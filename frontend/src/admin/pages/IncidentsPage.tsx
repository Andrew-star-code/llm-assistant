import { useInfiniteQuery } from "@tanstack/react-query";
import { useDeferredValue } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { SEVERITY_TONE, STATUS_TONE, tone } from "@/admin/incidents";
import { api, unwrap } from "@/api/client";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

const TYPES = [
  "system_error",
  "model_report",
  "guard",
  "security",
  "model_health",
  "rag_degraded",
  "kb_index",
  "worker_failed",
];
const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";

/** Инциденты (§13.5): фильтры в адресной строке, свежие сверху, переход в карточку. */
export function IncidentsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "open";
  const type = params.get("type") ?? "";
  const severity = params.get("severity") ?? "";
  const q = useDeferredValue(params.get("q") ?? "");
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  const incidents = useInfiniteQuery({
    queryKey: ["admin", "incidents", status, type, severity, q],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/incidents", {
          params: {
            query: {
              status: status === "all" ? undefined : status,
              type: type || undefined,
              severity: severity || undefined,
              q: q || undefined,
              cursor: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: 30_000,
  });
  const items = incidents.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.incidents")}</h1>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select
          aria-label={t("admin.incidents.status")}
          className={SELECT}
          value={status}
          onChange={(e) => {
            set("status", e.target.value === "open" ? "" : e.target.value);
          }}
        >
          <option value="open">{t("admin.incidents.open")}</option>
          {(["new", "in_progress", "resolved", "false_positive"] as const).map((s) => (
            <option key={s} value={s}>
              {t(`admin.incidents.statuses.${s}`)}
            </option>
          ))}
          <option value="all">{t("admin.incidents.any")}</option>
        </select>
        <select
          aria-label={t("admin.incidents.type")}
          className={SELECT}
          value={type}
          onChange={(e) => {
            set("type", e.target.value);
          }}
        >
          <option value="">
            {t("admin.incidents.type")}: {t("admin.incidents.any")}
          </option>
          {TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`admin.incidents.types.${x}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("admin.incidents.severity")}
          className={SELECT}
          value={severity}
          onChange={(e) => {
            set("severity", e.target.value);
          }}
        >
          <option value="">
            {t("admin.incidents.severity")}: {t("admin.incidents.any")}
          </option>
          {(["critical", "high", "medium", "warning", "low"] as const).map((x) => (
            <option key={x} value={x}>
              {t(`admin.incidents.severities.${x}`)}
            </option>
          ))}
        </select>
        <Input
          type="search"
          className="max-w-xs"
          aria-label={t("admin.incidents.search")}
          placeholder={t("admin.incidents.search")}
          value={params.get("q") ?? ""}
          onChange={(e) => {
            set("q", e.target.value);
          }}
        />
      </div>
      <Table
        head={[
          t("admin.incidents.lastSeen"),
          t("admin.incidents.severity"),
          t("admin.incidents.title"),
          t("admin.incidents.occurrences"),
          t("admin.incidents.status"),
          t("admin.incidents.assignee"),
        ]}
      >
        {items.map((i) => (
          <tr key={i.id} data-testid="incident-row">
            <Td className="whitespace-nowrap">{formatDateTime(i.last_seen)}</Td>
            <Td>
              <Badge tone={tone(SEVERITY_TONE, i.severity)}>
                {t(`admin.incidents.severities.${i.severity}`, { defaultValue: i.severity })}
              </Badge>
            </Td>
            <Td>
              <Link to={`/admin/incidents/${i.id}`} className="font-medium hover:underline">
                {i.title}
              </Link>
              <div className="text-xs text-muted-foreground">
                {t(`admin.incidents.types.${i.type}`, { defaultValue: i.type })}
                {i.user ? ` · ${i.user.full_name}` : ""}
              </div>
            </Td>
            <Td className="tabular-nums">{i.occurrences}</Td>
            <Td>
              <Badge tone={tone(STATUS_TONE, i.status)}>
                {t(`admin.incidents.statuses.${i.status}`, { defaultValue: i.status })}
              </Badge>
            </Td>
            <Td className="text-xs">{i.assignee?.full_name ?? "—"}</Td>
          </tr>
        ))}
      </Table>
      {incidents.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.incidents.empty")}</p>
      )}
      <LoadMore
        hasMore={incidents.hasNextPage}
        loading={incidents.isFetchingNextPage}
        onClick={() => {
          void incidents.fetchNextPage();
        }}
      />
    </section>
  );
}
