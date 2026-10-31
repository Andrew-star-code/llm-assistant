import { useInfiniteQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { useTranslation } from "react-i18next";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

type Filter = "all" | "success" | "failure";

/** Журнал входов (§13.4): все попытки с точной причиной отказа. Правила риска — этап 7. */
export function LoginsPage() {
  const { t } = useTranslation();
  const [login, setLogin] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const deferredLogin = useDeferredValue(login.trim());
  const success = filter === "all" ? undefined : filter === "success";
  const events = useInfiniteQuery({
    queryKey: ["admin", "logins", deferredLogin, filter],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/logins", {
          params: { query: { login: deferredLogin || undefined, success, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.logins")}</h1>
      <div className="flex flex-wrap gap-3">
        <Input
          type="search"
          className="max-w-xs"
          placeholder={t("admin.logins.filterLogin")}
          aria-label={t("admin.logins.filterLogin")}
          value={login}
          onChange={(e) => {
            setLogin(e.target.value);
          }}
        />
        <select
          aria-label={t("admin.logins.result")}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value as Filter);
          }}
        >
          <option value="all">{t("admin.logins.all")}</option>
          <option value="success">{t("admin.logins.success")}</option>
          <option value="failure">{t("admin.logins.failure")}</option>
        </select>
      </div>
      <Table
        head={[
          t("admin.logins.time"),
          t("admin.users.login"),
          "IP",
          t("admin.logins.method"),
          t("admin.logins.result"),
          "User-Agent",
        ]}
      >
        {items.map((e) => (
          <tr key={e.id}>
            <Td>{formatDateTime(e.ts)}</Td>
            <Td>{e.login_attempted}</Td>
            <Td>{e.ip ?? "—"}</Td>
            <Td>{e.method}</Td>
            <Td>
              {e.success ? (
                <Badge tone="ok">{t("admin.logins.success")}</Badge>
              ) : (
                <Badge tone="bad">{t(`failure.${e.failure_reason ?? "unknown"}`)}</Badge>
              )}
            </Td>
            <Td className="max-w-xs truncate text-xs text-muted-foreground">
              {e.user_agent ?? "—"}
            </Td>
          </tr>
        ))}
      </Table>
      <LoadMore
        hasMore={events.hasNextPage}
        loading={events.isFetchingNextPage}
        onClick={() => {
          void events.fetchNextPage();
        }}
      />
    </section>
  );
}
