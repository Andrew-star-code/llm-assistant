import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { SearchSettingsCard } from "@/admin/components/SearchSettingsCard";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { kbKeys } from "@/features/kb/api";
import { formatDateTime } from "@/lib/format";

/** Админка «Базы знаний» (§13.2): общие и ролевые базы, создание базы с ролями. */
export function KbListPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const bases = useQuery({
    queryKey: kbKeys.admin,
    queryFn: async () => unwrap(await api.GET("/api/admin/kb")),
  });
  const canCreate = bases.data === undefined || bases.data.every((b) => b.can_edit);
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.kb")}</h1>
      <Table
        head={[
          t("admin.kb.name"),
          t("admin.kb.level"),
          t("admin.kb.roles"),
          t("admin.kb.documents"),
          t("admin.kb.created"),
        ]}
      >
        {(bases.data ?? []).map((kb) => (
          <tr key={kb.id} data-testid="kb-row">
            <Td>
              <Link to={`/admin/kb/${kb.id}`} className="font-medium hover:underline">
                {kb.name}
              </Link>
              <div className="text-xs text-muted-foreground">{kb.code}</div>
            </Td>
            <Td>{t(`admin.kb.levels.${kb.level}`)}</Td>
            <Td>{kb.roles.map((r) => r.name).join(", ") || "—"}</Td>
            <Td>
              <span className="flex flex-wrap gap-1">
                <Badge tone="ok">
                  {t("kb.status.ready")}: {kb.documents.ready}
                </Badge>
                {kb.documents.queued + kb.documents.processing > 0 && (
                  <Badge tone="warn">
                    {t("kb.status.processing")}: {kb.documents.queued + kb.documents.processing}
                  </Badge>
                )}
                {kb.documents.error > 0 && (
                  <Badge tone="bad">
                    {t("kb.status.error")}: {kb.documents.error}
                  </Badge>
                )}
              </span>
            </Td>
            <Td>{formatDateTime(kb.created_at)}</Td>
          </tr>
        ))}
      </Table>
      {hasPermission(me, "admin.kb.manage") && <SearchSettingsCard />}
      {canCreate && (
        <CreateKbForm
          onCreated={() => {
            void queryClient.invalidateQueries({ queryKey: kbKeys.admin });
          }}
        />
      )}
    </section>
  );
}

function CreateKbForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [level, setLevel] = useState<"global" | "role">("global");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const roles = useQuery({
    queryKey: ["admin", "roles"],
    queryFn: async () => unwrap(await api.GET("/api/admin/roles")),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/kb", {
          body: {
            code,
            name,
            description: description || null,
            level,
            role_ids: level === "role" ? roleIds : [],
          },
        }),
      ),
    onSuccess: () => {
      setCode("");
      setName("");
      setDescription("");
      setRoleIds([]);
      onCreated();
    },
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
      data-testid="kb-create-form"
    >
      <h2 className="font-medium">{t("admin.kb.create")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          required
          placeholder={t("admin.kb.code")}
          aria-label={t("admin.kb.code")}
          pattern="[a-z0-9][a-z0-9_\-]*"
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
          }}
        />
        <Input
          required
          placeholder={t("admin.kb.name")}
          aria-label={t("admin.kb.name")}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </div>
      <Input
        placeholder={t("admin.kb.description")}
        aria-label={t("admin.kb.description")}
        value={description}
        onChange={(e) => {
          setDescription(e.target.value);
        }}
      />
      <select
        aria-label={t("admin.kb.level")}
        className="h-9 w-fit rounded-md border border-border bg-background px-2 text-sm"
        value={level}
        onChange={(e) => {
          setLevel(e.target.value as "global" | "role");
        }}
      >
        <option value="global">{t("admin.kb.levels.global")}</option>
        <option value="role">{t("admin.kb.levels.role")}</option>
      </select>
      {level === "role" && (
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <legend className="mb-1 text-xs text-muted-foreground">{t("admin.kb.whoSees")}</legend>
          {(roles.data ?? [])
            .filter((r) => r.kind !== "system")
            .map((r) => (
              <label key={r.id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={roleIds.includes(r.id)}
                  onChange={(e) => {
                    setRoleIds((prev) =>
                      e.target.checked ? [...prev, r.id] : prev.filter((id) => id !== r.id),
                    );
                  }}
                />
                {r.name}
              </label>
            ))}
        </fieldset>
      )}
      {create.isError && (
        <p role="alert" className="text-sm text-red-600">
          {create.error instanceof ApiError ? create.error.message : t("common.loadError")}
        </p>
      )}
      <Button type="submit" className="w-fit" disabled={create.isPending}>
        {t("admin.kb.createButton")}
      </Button>
    </form>
  );
}
