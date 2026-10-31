import { useMutation } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function Ok({ ok }: { ok: boolean }) {
  const { t } = useTranslation();
  return <Badge tone={ok ? "ok" : "bad"}>{ok ? t("admin.ad.ok") : t("admin.ad.error")}</Badge>;
}

/** Диагностика AD (§6.7): то же, что `ad check`, без проверки пароля. */
export function AdDiagnosticsPage() {
  const { t } = useTranslation();
  const [login, setLogin] = useState("");
  const run = useMutation({
    mutationFn: async (value: string) =>
      unwrap(await api.POST("/api/admin/ad/diagnostics", { body: { login: value } })),
  });
  const onSubmit = (event: SubmitEvent) => {
    event.preventDefault();
    run.mutate(login);
  };
  const r = run.data;

  return (
    <section className="flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">{t("admin.nav.ad")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.ad.hint")}</p>
      </div>
      <form className="flex gap-2" onSubmit={onSubmit}>
        <Input
          required
          className="max-w-xs"
          placeholder="ivanov"
          aria-label={t("admin.users.login")}
          value={login}
          onChange={(e) => {
            setLogin(e.target.value);
          }}
        />
        <Button type="submit" disabled={run.isPending}>
          {t("admin.ad.run")}
        </Button>
      </form>
      {run.error && (
        <p role="alert" className="text-sm text-red-600">
          {run.error instanceof ApiError ? run.error.message : t("common.loadError")}
        </p>
      )}
      {r && (
        <div className="flex flex-col gap-5 text-sm" data-testid="ad-report">
          <section>
            <h2 className="mb-2 font-semibold">{t("admin.ad.controllers")}</h2>
            <ul className="flex flex-col gap-1">
              {r.controllers.map((c) => (
                <li key={c.url} className="flex items-center gap-2">
                  <Ok ok={c.ok} /> <code>{c.url}</code>
                  <span className="text-muted-foreground">
                    {c.duration_ms} {t("admin.ad.ms")}
                  </span>
                  {c.error && <span className="text-red-600">{c.error}</span>}
                </li>
              ))}
            </ul>
          </section>
          <p className="flex items-center gap-2">
            {t("admin.ad.serviceBind")}: <Ok ok={r.service_bind.ok} />
            {r.service_bind.error && <span className="text-red-600">{r.service_bind.error}</span>}
          </p>
          {r.service_bind.ok && !r.user_found && <p>{t("admin.ad.notFound")}</p>}
          {r.entry && (
            <>
              <dl className="grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">DN</dt>
                <dd className="break-all">{r.entry.dn}</dd>
                <dt className="text-muted-foreground">{t("admin.ad.enabled")}</dt>
                <dd>{r.entry.disabled ? t("common.no") : t("common.yes")}</dd>
                <dt className="text-muted-foreground">{t("admin.ad.accessGroup")}</dt>
                <dd>{r.entry.in_access_group ? t("common.yes") : t("common.no")}</dd>
                <dt className="text-muted-foreground">{t("admin.ad.fullName")}</dt>
                <dd>{r.full_name}</dd>
                <dt className="text-muted-foreground">{t("admin.ad.address")}</dt>
                <dd>{r.address ?? t("addressForm.formalPreview")}</dd>
                <dt className="text-muted-foreground">{t("admin.users.department")}</dt>
                <dd>{r.department ?? "—"}</dd>
                <dt className="text-muted-foreground">{t("profile.roles")}</dt>
                <dd>{r.roles.map((x) => `${x.name} [${x.source}]`).join(", ") || "—"}</dd>
              </dl>
              <section>
                <h2 className="mb-2 font-semibold">{t("admin.ad.attributes")}</h2>
                <dl className="grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1">
                  {Object.entries(r.entry.attributes).map(([name, value]) => (
                    <div key={name} className="contents">
                      <dt className="font-mono text-xs text-muted-foreground">{name}</dt>
                      <dd>{value ?? "—"}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            </>
          )}
          <p className="font-medium">{r.ok ? t("admin.ad.canLogin") : t("admin.ad.cannotLogin")}</p>
        </div>
      )}
    </section>
  );
}
