import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-words whitespace-pre-line">{value || "—"}</dd>
    </div>
  );
}

/** Карточка пользователя (§13.2): данные AD, роли, сессии, входы; блокировка, разлогин, роли. */
export function UserCardPage() {
  const { t } = useTranslation();
  const { userId = "" } = useParams();
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const key = ["admin", "user", userId];
  const card = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/users/{user_id}", { params: { path: { user_id: userId } } }),
      ),
  });
  const roles = useQuery({
    queryKey: ["admin", "roles"],
    queryFn: async () => unwrap(await api.GET("/api/admin/roles")),
    enabled: hasPermission(me, "admin.roles.manage"),
  });
  const [blockReason, setBlockReason] = useState("");
  const [blockUntil, setBlockUntil] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const onError = (e: Error) => {
    setError(e instanceof ApiError ? e.message : t("common.loadError"));
  };
  const path = { params: { path: { user_id: userId } } };

  const block = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/users/{user_id}/block", {
          ...path,
          body: {
            reason: blockReason,
            until: blockUntil ? new Date(blockUntil).toISOString() : null,
          },
        }),
      ),
    onSuccess: () => {
      setBlockReason("");
      setBlockUntil("");
      setError(null);
      void refresh();
    },
    onError,
  });
  const unblock = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/admin/users/{user_id}/unblock", path));
    },
    onSuccess: () => void refresh(),
    onError,
  });
  const logoutAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/admin/users/{user_id}/logout", path)),
    onSuccess: () => void refresh(),
    onError,
  });
  const revoke = useMutation({
    mutationFn: async (sessionId: string) => {
      unwrap(
        await api.DELETE("/api/admin/sessions/{session_id}", {
          params: { path: { session_id: sessionId } },
        }),
      );
    },
    onSuccess: () => void refresh(),
    onError,
  });
  const setRoles = useMutation({
    mutationFn: async (roleIds: string[]) =>
      unwrap(
        await api.PUT("/api/admin/users/{user_id}/roles", { ...path, body: { role_ids: roleIds } }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      setError(null);
    },
    onError,
  });

  if (card.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (card.isError) return <p className="text-red-600">{t("common.loadError")}</p>;
  const u = card.data;
  const manualRoleIds = new Set(
    (roles.data ?? [])
      .filter((r) => u.roles.some((ur) => ur.code === r.code && ur.source === "manual"))
      .map((r) => r.id),
  );
  const toggleRole = (roleId: string) => {
    const next = new Set(manualRoleIds);
    if (next.has(roleId)) next.delete(roleId);
    else next.add(roleId);
    setRoles.mutate([...next]);
  };
  const onBlock = (event: SubmitEvent) => {
    event.preventDefault();
    block.mutate();
  };

  return (
    <section className="flex max-w-5xl flex-col gap-8">
      <header className="flex items-center gap-4">
        <Avatar
          name={u.full_name}
          src={u.has_photo ? `/api/admin/users/${u.id}/photo` : null}
          className="size-16 text-lg"
        />
        <div className="flex-1">
          <h1 className="text-xl font-semibold">{u.full_name}</h1>
          <p className="text-sm text-muted-foreground">
            {[u.title, u.department].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="flex gap-2">
          {u.ad_disabled && <Badge tone="bad">{t("admin.users.adDisabled")}</Badge>}
          {u.is_blocked && <Badge tone="bad">{t("admin.users.blocked")}</Badge>}
        </div>
      </header>

      {error && (
        <p role="alert" className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        <dl>
          <Row label={t("admin.users.login")} value={u.login} />
          <Row label="UPN" value={u.upn} />
          <Row label={t("profile.email")} value={u.email} />
          <Row label={t("profile.company")} value={u.company} />
          <Row label={t("profile.office")} value={u.office} />
          <Row label={t("profile.phone")} value={u.phone} />
          <Row label={t("profile.mobile")} value={u.mobile} />
          <Row label={t("profile.manager")} value={u.manager_name} />
          <Row label={t("admin.users.employeeId")} value={u.employee_id} />
          <Row label={t("admin.users.lastLogin")} value={formatDateTime(u.last_login_at)} />
          <Row label={t("admin.users.synced")} value={formatDateTime(u.synced_at)} />
          <Row label={t("admin.users.groups")} value={u.ad_groups.join("\n")} />
        </dl>

        <div className="flex flex-col gap-6">
          <section>
            <h2 className="mb-2 font-semibold">{t("profile.roles")}</h2>
            <ul className="flex flex-wrap gap-2">
              {u.roles.map((r) => (
                <li
                  key={`${r.code}-${r.source}`}
                  className="rounded-full border border-border px-3 py-1 text-xs"
                >
                  {r.name}{" "}
                  <span className="text-muted-foreground">· {t(`roleSource.${r.source}`)}</span>
                </li>
              ))}
            </ul>
            {roles.data && (
              <fieldset className="mt-3 flex flex-col gap-1" disabled={setRoles.isPending}>
                <legend className="mb-1 text-sm text-muted-foreground">
                  {t("admin.users.manualRoles")}
                </legend>
                {roles.data
                  .filter((r) => r.kind !== "department")
                  .map((r) => (
                    <label key={r.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={manualRoleIds.has(r.id)}
                        onChange={() => {
                          toggleRole(r.id);
                        }}
                      />
                      {r.name} <span className="text-xs text-muted-foreground">({r.code})</span>
                    </label>
                  ))}
              </fieldset>
            )}
          </section>

          {hasPermission(me, "admin.users.block") && (
            <section>
              <h2 className="mb-2 font-semibold">{t("admin.users.blocking")}</h2>
              {u.is_blocked ? (
                <div className="flex flex-col gap-2 text-sm">
                  <p>
                    {u.blocked_reason}
                    {u.blocked_until &&
                      ` — ${t("admin.users.until")} ${formatDateTime(u.blocked_until)}`}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="self-start"
                    onClick={() => {
                      unblock.mutate();
                    }}
                  >
                    {t("admin.users.unblock")}
                  </Button>
                </div>
              ) : (
                <form className="flex flex-col gap-2" onSubmit={onBlock}>
                  <Input
                    required
                    placeholder={t("admin.users.blockReason")}
                    aria-label={t("admin.users.blockReason")}
                    value={blockReason}
                    onChange={(e) => {
                      setBlockReason(e.target.value);
                    }}
                  />
                  <label className="flex items-center gap-2 text-sm text-muted-foreground">
                    {t("admin.users.until")}
                    <Input
                      type="datetime-local"
                      className="w-auto"
                      value={blockUntil}
                      onChange={(e) => {
                        setBlockUntil(e.target.value);
                      }}
                    />
                  </label>
                  <Button type="submit" size="sm" className="self-start" disabled={block.isPending}>
                    {t("admin.users.block")}
                  </Button>
                </form>
              )}
            </section>
          )}
        </div>
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">{t("admin.users.sessions")}</h2>
          {hasPermission(me, "admin.users.logout") && u.sessions.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                logoutAll.mutate();
              }}
            >
              {t("admin.users.logoutAll")}
            </Button>
          )}
        </div>
        <Table head={[t("admin.users.created"), "IP", "User-Agent", t("admin.users.lastSeen"), ""]}>
          {u.sessions.map((s) => (
            <tr key={s.id}>
              <Td>{formatDateTime(s.created_at)}</Td>
              <Td>{s.ip ?? "—"}</Td>
              <Td className="max-w-xs truncate">{s.user_agent ?? "—"}</Td>
              <Td>{formatDateTime(s.last_seen_at)}</Td>
              <Td>
                {hasPermission(me, "admin.users.logout") && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      revoke.mutate(s.id);
                    }}
                  >
                    {t("admin.users.revoke")}
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      </section>

      <section>
        <h2 className="mb-2 font-semibold">{t("admin.users.recentLogins")}</h2>
        <Table
          head={[t("admin.logins.time"), "IP", t("admin.logins.method"), t("admin.logins.result")]}
        >
          {u.recent_logins.map((e) => (
            <tr key={e.id}>
              <Td>{formatDateTime(e.ts)}</Td>
              <Td>{e.ip ?? "—"}</Td>
              <Td>{e.method}</Td>
              <Td>
                {e.success ? (
                  <Badge tone="ok">{t("admin.logins.success")}</Badge>
                ) : (
                  <Badge tone="bad">{t(`failure.${e.failure_reason ?? "unknown"}`)}</Badge>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      </section>
    </section>
  );
}
