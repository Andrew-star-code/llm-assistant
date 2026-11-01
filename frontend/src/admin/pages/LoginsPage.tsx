import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { useTranslation } from "react-i18next";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

type Filter = "all" | "success" | "failure" | "flagged" | "unreviewed";

const FLAG_TONE: Record<string, "warn" | "muted"> = {
  after_failures: "warn",
  concurrent_subnets: "warn",
  blocked_attempt: "warn",
  new_subnet: "muted",
  off_hours: "muted",
};

/** Журнал входов (§13.4): попытки с точной причиной отказа, флаги риска, проверка, блокировка IP. */
export function LoginsPage() {
  const { t } = useTranslation();
  const [login, setLogin] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const deferredLogin = useDeferredValue(login.trim());
  const { data: me } = useMe();
  const canManage = hasPermission(me, "admin.security.manage");
  const queryClient = useQueryClient();
  const success = filter === "success" ? true : filter === "failure" ? false : undefined;
  const flagged = filter === "flagged" || filter === "unreviewed" ? true : undefined;
  const unreviewed = filter === "unreviewed" ? true : undefined;
  const review = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/admin/logins/{event_id}/review", {
          params: { path: { event_id: id } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "logins"] });
    },
  });
  const blockIp = useMutation({
    mutationFn: async ({ ip, reason }: { ip: string; reason: string }) =>
      unwrap(await api.POST("/api/admin/ip-blocks", { body: { cidr: ip, reason, minutes: null } })),
  });
  const events = useInfiniteQuery({
    queryKey: ["admin", "logins", deferredLogin, filter],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/logins", {
          params: {
            query: {
              login: deferredLogin || undefined,
              success,
              flagged,
              unreviewed,
              cursor: pageParam,
            },
          },
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
          <option value="flagged">{t("admin.logins.onlyFlagged")}</option>
          <option value="unreviewed">{t("admin.logins.unreviewed")}</option>
        </select>
      </div>
      <Table
        head={[
          t("admin.logins.time"),
          t("admin.users.login"),
          "IP",
          t("admin.logins.method"),
          t("admin.logins.result"),
          t("admin.logins.flags"),
          "User-Agent",
        ]}
      >
        {items.map((e) => (
          <tr key={e.id} data-testid="login-row">
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
            <Td>
              <div className="flex flex-wrap items-center gap-1">
                {e.risk_flags.map((f) => (
                  <Badge key={f} tone={FLAG_TONE[f] ?? "muted"}>
                    {t(`admin.logins.flagNames.${f}`, { defaultValue: f })}
                  </Badge>
                ))}
                {e.reviewed_at && (
                  <span className="text-xs text-muted-foreground">
                    ✓ {t("admin.logins.reviewed")}
                  </span>
                )}
                {canManage && e.risk_flags.length > 0 && !e.reviewed_at && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      review.mutate(e.id);
                    }}
                  >
                    {t("admin.logins.review")}
                  </Button>
                )}
                {canManage && e.ip && !e.success && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      const reason = window.prompt(t("admin.logins.blockReason"));
                      if (reason && e.ip) blockIp.mutate({ ip: e.ip, reason });
                    }}
                  >
                    {t("admin.logins.blockIp")}
                  </Button>
                )}
              </div>
            </Td>
            <Td className="max-w-xs truncate text-xs text-muted-foreground">
              {e.user_agent ?? "—"}
            </Td>
          </tr>
        ))}
      </Table>
      {blockIp.isSuccess && (
        <p role="status" className="text-sm">
          {t("admin.logins.ipBlocked", { ip: blockIp.data.cidr })}
        </p>
      )}
      {(blockIp.error ?? review.error) && (
        <p role="alert" className="text-sm text-red-600">
          {(blockIp.error ?? review.error) instanceof ApiError
            ? (blockIp.error ?? review.error)?.message
            : t("common.loadError")}
        </p>
      )}
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
