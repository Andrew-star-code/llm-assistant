import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

type BulkOut = Schemas["BulkOut"];

/** Логины и e-mail из вставленного текста: строки, запятые, точки с запятой, табуляции. */
function parseIdentifiers(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function BulkResult({ result }: { result: BulkOut }) {
  const { t } = useTranslation();
  return (
    <div role="status" className="flex flex-col gap-1 text-sm" data-testid="bulk-result">
      <p>
        {t("admin.roles.result", {
          added: result.added.length,
          already: result.already.length,
          created: result.created.length,
        })}
      </p>
      {result.not_found.length > 0 && (
        <p className="text-red-600">
          {t("admin.roles.notFound", { list: result.not_found.join(", ") })}
        </p>
      )}
    </div>
  );
}

/** Роль: участники, массовое добавление списком логинов или e-mail, снятие, правка. */
export function RolePage() {
  const { roleId = "" } = useParams();
  const { t } = useTranslation();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canManage = hasPermission(me, "admin.roles.manage");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const role = useQuery({
    queryKey: ["admin", "role", roleId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/roles/{role_id}", { params: { path: { role_id: roleId } } }),
      ),
  });
  const members = useInfiniteQuery({
    queryKey: ["admin", "role-members", roleId, query],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/roles/{role_id}/members", {
          params: {
            path: { role_id: roleId },
            query: { q: query || undefined, cursor: pageParam },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "role", roleId] });
    void queryClient.invalidateQueries({ queryKey: ["admin", "role-members", roleId] });
    void queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
  };
  const add = useMutation({
    mutationFn: async (identifiers: string[]) =>
      unwrap(
        await api.POST("/api/admin/roles/{role_id}/members", {
          params: { path: { role_id: roleId } },
          body: { identifiers },
        }),
      ),
    onSuccess: (result) => {
      // В поле остаются только ненайденные — их можно поправить и отправить снова.
      setText(result.not_found.join("\n"));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (userIds: string[]) =>
      unwrap(
        await api.POST("/api/admin/roles/{role_id}/members/remove", {
          params: { path: { role_id: roleId } },
          body: { user_ids: userIds },
        }),
      ),
    onSuccess: () => {
      setSelected(new Set());
      refresh();
    },
  });
  const drop = useMutation({
    mutationFn: async () => {
      unwrap(
        await api.DELETE("/api/admin/roles/{role_id}", { params: { path: { role_id: roleId } } }),
      );
    },
  });

  const r = role.data;
  const items = members.data?.pages.flatMap((p) => p.items) ?? [];
  const identifiers = parseIdentifiers(text);
  const error = add.error ?? remove.error ?? drop.error;
  if (!r) return null;

  return (
    <section className="flex max-w-4xl flex-col gap-4" data-testid="role-page">
      <Link to="/admin/roles" className="text-sm text-muted-foreground hover:underline">
        ← {t("admin.nav.roles")}
      </Link>
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{r.name}</h1>
        <p className="text-sm text-muted-foreground">
          {r.code} · {t(`admin.roles.kinds.${r.kind}`, { defaultValue: r.kind })} ·{" "}
          {t("admin.roles.usersCount", { count: r.users })}
        </p>
        {(r.knowledge_bases.length > 0 || r.scenarios.length > 0) && (
          <p className="text-xs text-muted-foreground">
            {t("admin.roles.usedBy", { list: [...r.knowledge_bases, ...r.scenarios].join(", ") })}
          </p>
        )}
      </header>

      {canManage && r.kind !== "department" && (
        <div className="flex flex-col gap-2 rounded-lg border border-border p-4">
          <h2 className="font-medium">{t("admin.roles.bulkTitle")}</h2>
          <p className="text-xs text-muted-foreground">{t("admin.roles.bulkHint")}</p>
          <textarea
            className="min-h-32 w-full rounded-md border border-border bg-background p-2 font-mono text-sm"
            aria-label={t("admin.roles.bulkTitle")}
            placeholder={"ivanov\npetrov@corp.local\nCORP\\kim"}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            data-testid="bulk-input"
          />
          <Button
            className="w-fit"
            disabled={identifiers.length === 0 || add.isPending}
            onClick={() => {
              add.mutate(identifiers);
            }}
          >
            {t("admin.roles.bulkAdd", { count: identifiers.length })}
          </Button>
          {add.data && <BulkResult result={add.data} />}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label={t("admin.roles.searchMembers")}
          placeholder={t("admin.roles.searchMembers")}
          className="max-w-xs"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
          }}
        />
        {canManage && selected.size > 0 && (
          <Button
            variant="outline"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate([...selected]);
            }}
          >
            {t("admin.roles.removeSelected", { count: selected.size })}
          </Button>
        )}
      </div>
      <Table
        head={[
          "",
          t("admin.users.name"),
          t("admin.users.department"),
          t("admin.roles.source"),
          t("admin.users.lastLogin"),
        ]}
      >
        {items.map((m) => (
          <tr key={m.id} data-testid="role-member">
            <Td>
              {canManage && m.source === "manual" && (
                <input
                  type="checkbox"
                  aria-label={m.full_name}
                  checked={selected.has(m.id)}
                  onChange={(e) => {
                    const next = new Set(selected);
                    if (e.target.checked) next.add(m.id);
                    else next.delete(m.id);
                    setSelected(next);
                  }}
                />
              )}
            </Td>
            <Td>
              <Link to={`/admin/users/${m.id}`} className="hover:underline">
                {m.full_name}
              </Link>
              <div className="text-xs text-muted-foreground">{m.login}</div>
            </Td>
            <Td>{m.department ?? "—"}</Td>
            <Td>
              <Badge tone="muted">
                {t(`admin.roles.sources.${m.source}`, { defaultValue: m.source })}
              </Badge>
            </Td>
            <Td className="whitespace-nowrap">
              {m.last_login_at ? formatDateTime(m.last_login_at) : t("admin.roles.neverLoggedIn")}
            </Td>
          </tr>
        ))}
      </Table>
      {members.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.roles.empty")}</p>
      )}
      <LoadMore
        hasMore={members.hasNextPage}
        loading={members.isFetchingNextPage}
        onClick={() => {
          void members.fetchNextPage();
        }}
      />

      {canManage && r.editable && (
        <Button
          variant="outline"
          className="w-fit text-red-600"
          disabled={drop.isPending}
          onClick={() => {
            void drop
              .mutateAsync()
              .then(() => {
                void queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
                return navigate("/admin/roles", { replace: true });
              })
              .catch(() => undefined);
          }}
        >
          {t("admin.roles.delete")}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error instanceof ApiError ? error.message : t("common.loadError")}
        </p>
      )}
    </section>
  );
}
