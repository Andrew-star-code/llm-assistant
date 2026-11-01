import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";

/** «Роли»: роли назначаются вручную (отдел из AD не получить), свои роли создаются здесь. */
export function RolesPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const roles = useQuery({
    queryKey: ["admin", "roles"],
    queryFn: async () => unwrap(await api.GET("/api/admin/roles")),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/admin/roles", { body: { code, name, description: null } })),
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    void create
      .mutateAsync()
      .then((role) => {
        void queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
        return navigate(`/admin/roles/${role.id}`);
      })
      .catch(() => undefined);
  };
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.roles")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.roles.hint")}</p>
      <Table head={[t("admin.roles.name"), t("admin.roles.kind"), t("admin.roles.users")]}>
        {(roles.data ?? []).map((r) => (
          <tr key={r.id} data-testid="role-row">
            <Td>
              <Link to={`/admin/roles/${r.id}`} className="font-medium hover:underline">
                {r.name}
              </Link>
              <div className="text-xs text-muted-foreground">{r.code}</div>
            </Td>
            <Td>
              <Badge tone={r.kind === "system" ? "warn" : "muted"}>
                {t(`admin.roles.kinds.${r.kind}`, { defaultValue: r.kind })}
              </Badge>
            </Td>
            <Td className="tabular-nums">{r.users}</Td>
          </tr>
        ))}
      </Table>
      {hasPermission(me, "admin.roles.manage") && (
        <form
          onSubmit={submit}
          className="flex flex-col gap-3 rounded-lg border border-border p-4"
          data-testid="role-create-form"
        >
          <h2 className="font-medium">{t("admin.roles.create")}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              required
              aria-label={t("admin.roles.name")}
              placeholder={t("admin.roles.namePlaceholder")}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
              }}
            />
            <Input
              required
              aria-label={t("admin.roles.code")}
              placeholder={t("admin.roles.codePlaceholder")}
              pattern="[A-Za-z0-9][A-Za-z0-9_\-]*"
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
              }}
            />
          </div>
          {create.isError && (
            <p role="alert" className="text-sm text-red-600">
              {create.error instanceof ApiError ? create.error.message : t("common.loadError")}
            </p>
          )}
          <Button type="submit" className="w-fit" disabled={create.isPending}>
            {t("admin.roles.createButton")}
          </Button>
        </form>
      )}
    </section>
  );
}
