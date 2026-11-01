import { useInfiniteQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

export function UsersPage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const q = useDeferredValue(query.trim());
  const users = useInfiniteQuery({
    queryKey: ["admin", "users", q],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/users", {
          params: { query: { q: q || undefined, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = users.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.users")}</h1>
      <Input
        type="search"
        placeholder={t("admin.users.search")}
        aria-label={t("admin.users.search")}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
        }}
        className="max-w-md"
      />
      <Table
        head={[
          t("admin.users.name"),
          t("admin.users.login"),
          t("admin.users.department"),
          t("admin.users.status"),
          t("admin.users.lastLogin"),
        ]}
      >
        {items.map((u) => (
          <tr key={u.id}>
            <Td>
              <Link
                to={`/admin/users/${u.id}`}
                className="font-medium text-primary hover:underline"
              >
                {u.full_name}
              </Link>
              <div className="text-xs text-muted-foreground">{u.title}</div>
            </Td>
            <Td>{u.login}</Td>
            <Td>{u.department ?? "—"}</Td>
            <Td>
              {u.ad_disabled ? (
                <Badge tone="bad">{t("admin.users.adDisabled")}</Badge>
              ) : u.is_blocked ? (
                <Badge tone="bad">{t("admin.users.blocked")}</Badge>
              ) : (
                <Badge tone="ok">{t("admin.users.active")}</Badge>
              )}
            </Td>
            <Td>{formatDateTime(u.last_login_at)}</Td>
          </tr>
        ))}
      </Table>
      {users.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("common.nothingFound")}</p>
      )}
      <LoadMore
        hasMore={users.hasNextPage}
        loading={users.isFetchingNextPage}
        onClick={() => {
          void users.fetchNextPage();
        }}
      />
    </section>
  );
}
