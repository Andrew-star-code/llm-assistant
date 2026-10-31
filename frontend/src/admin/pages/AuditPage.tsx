import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { LoadMore } from "@/admin/components/LoadMore";
import { Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { formatDateTime } from "@/lib/format";

/** Журнал аудита (§13.6): кто, что, когда, над каким объектом, с какого IP. Только чтение. */
export function AuditPage() {
  const { t } = useTranslation();
  const audit = useInfiniteQuery({
    queryKey: ["admin", "audit"],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET("/api/admin/audit", { params: { query: { cursor: pageParam } } })),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = audit.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.audit")}</h1>
      <Table
        head={[
          t("admin.logins.time"),
          t("admin.audit.actor"),
          t("admin.audit.action"),
          t("admin.audit.target"),
          t("admin.audit.details"),
          "IP",
        ]}
      >
        {items.map((e) => (
          <tr key={e.id}>
            <Td>{formatDateTime(e.ts)}</Td>
            <Td>{e.actor_name ?? "—"}</Td>
            <Td>{t(`auditAction.${e.action}`, { defaultValue: e.action })}</Td>
            <Td className="text-xs">
              {e.target_type}: {e.target_id}
            </Td>
            <Td className="max-w-sm">
              <code className="break-all text-xs">{JSON.stringify(e.details)}</code>
            </Td>
            <Td>{e.ip ?? "—"}</Td>
          </tr>
        ))}
      </Table>
      {audit.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("common.nothingFound")}</p>
      )}
      <LoadMore
        hasMore={audit.hasNextPage}
        loading={audit.isFetchingNextPage}
        onClick={() => {
          void audit.fetchNextPage();
        }}
      />
    </section>
  );
}
