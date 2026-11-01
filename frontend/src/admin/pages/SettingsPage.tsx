import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, csrfToken, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type SettingsOut = Schemas["SettingsOut"];
type SettingsIn = Schemas["SettingsIn"];
type Field = keyof Schemas["SettingsValues"];

const QUERY_KEY = ["admin", "settings"] as const;
const FORMS = ["name_patronymic", "first_name", "full_name", "formal"] as const;
const AREA = "min-h-24 w-full rounded-md border border-border bg-background p-2 text-sm";

/** Логотип (multipart) с CSRF; ошибка — ApiError с текстом сервера. */
async function uploadLogo(file: File): Promise<SettingsOut> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/admin/settings/logo", {
    method: "POST",
    body: form,
    credentials: "same-origin",
    headers: { "X-CSRF-Token": await csrfToken() },
  });
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(response.status, error?.code ?? "upload_failed", error?.message ?? "");
  }
  return body as SettingsOut;
}

/** «Настройки» (§13.2): действуют без перезапуска, перекрывают конфиг, пишутся в аудит. */
export function SettingsPage() {
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/admin/settings")),
  });
  // Здесь, а не в форме: новые данные пересоздают форму, и её состояние теряется.
  const [saved, setSaved] = useState(false);
  if (!settings.data) return null;
  // Сохранили — форма пересоздаётся с новыми значениями (без синхронизации в эффекте).
  return (
    <SettingsForm
      key={JSON.stringify(settings.data)}
      initial={settings.data}
      saved={saved}
      setSaved={setSaved}
    />
  );
}

function SettingsForm({
  initial,
  saved,
  setSaved,
}: {
  initial: SettingsOut;
  saved: boolean;
  setSaved: (saved: boolean) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Schemas["SettingsValues"]>({
    app_name: initial.app_name,
    company_name: initial.company_name,
    notice_text: initial.notice_text,
    retention_days: initial.retention_days,
    max_file_mb: initial.max_file_mb,
    max_files_per_message: initial.max_files_per_message,
    default_address_form: initial.default_address_form,
    system_prompt: initial.system_prompt,
  });
  const [reaccept, setReaccept] = useState(false);
  const done = (data: SettingsOut) => {
    queryClient.setQueryData(QUERY_KEY, data);
    void queryClient.invalidateQueries({ queryKey: ["branding"] });
  };
  const save = useMutation({
    mutationFn: async (body: SettingsIn) => unwrap(await api.PUT("/api/admin/settings", { body })),
    onSuccess: (data) => {
      setSaved(true);
      done(data);
    },
  });
  const logo = useMutation({
    mutationFn: async (upload: File | null) =>
      upload ? uploadLogo(upload) : unwrap(await api.DELETE("/api/admin/settings/logo")),
    onSuccess: done,
  });

  const set = <K extends Field>(name: K, value: Schemas["SettingsValues"][K]) => {
    setSaved(false);
    setValues((prev) => ({ ...prev, [name]: value }));
  };
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    // Отправляем только изменённое: остальное остаётся как есть (в т. ч. «из конфигурации»).
    const body: SettingsIn = { require_notice_reaccept: reaccept };
    for (const key of Object.keys(values) as Field[]) {
      if (values[key] !== initial[key]) Object.assign(body, { [key]: values[key] });
    }
    save.mutate(body);
  };
  const reset = (name: Field) => {
    save.mutate(Object.assign({ require_notice_reaccept: false }, { [name]: null }));
  };
  const source = (name: Field) =>
    initial.overridden.includes(name) ? (
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        {t("admin.settings.overridden")} ·{" "}
        {t("admin.settings.fromConfig", {
          value:
            name === "system_prompt" || name === "notice_text"
              ? "…"
              : String(initial.defaults[name]),
        })}
        <button
          type="button"
          className="text-primary underline"
          onClick={() => {
            reset(name);
          }}
        >
          {t("admin.settings.reset")}
        </button>
      </span>
    ) : null;
  const error = save.error ?? logo.error;

  return (
    <form onSubmit={submit} className="flex max-w-3xl flex-col gap-5" data-testid="settings-form">
      <h1 className="text-xl font-semibold">{t("admin.nav.settings")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.settings.hint")}</p>

      <label className="flex flex-col gap-1 text-sm">
        {t("admin.settings.appName")}
        <Input
          value={values.app_name}
          onChange={(e) => {
            set("app_name", e.target.value);
          }}
        />
        {source("app_name")}
      </label>

      <div className="flex flex-col gap-1 text-sm">
        {t("admin.settings.logo")}
        <div className="flex flex-wrap items-center gap-2">
          {initial.has_logo && (
            <img
              src={`/api/branding/logo?v=${initial.logo_version ?? ""}`}
              alt={t("admin.settings.logo")}
              className="h-10 w-auto rounded border border-border"
            />
          )}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label={t("admin.settings.uploadLogo")}
            className="text-xs"
            onChange={(e) => {
              const picked = e.target.files?.[0];
              if (picked) logo.mutate(picked);
            }}
          />
          {initial.has_logo && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                logo.mutate(null);
              }}
            >
              {t("admin.settings.removeLogo")}
            </Button>
          )}
        </div>
        <span className="text-xs text-muted-foreground">{t("admin.settings.logoHint")}</span>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("admin.settings.companyName")}
        <Input
          value={values.company_name}
          onChange={(e) => {
            set("company_name", e.target.value);
          }}
        />
        {source("company_name")}
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t("admin.settings.notice")}
        <textarea
          className={AREA}
          value={values.notice_text}
          onChange={(e) => {
            set("notice_text", e.target.value);
          }}
        />
        {source("notice_text")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={reaccept}
          onChange={(e) => {
            setReaccept(e.target.checked);
          }}
        />
        {t("admin.settings.reaccept")}
      </label>

      <div className="grid gap-4 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          {t("admin.settings.retention")}
          <Input
            type="number"
            min={0}
            max={3650}
            value={values.retention_days}
            onChange={(e) => {
              set("retention_days", Number(e.target.value));
            }}
          />
          {source("retention_days")}
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("admin.settings.maxFileMb")}
          <Input
            type="number"
            min={1}
            max={500}
            value={values.max_file_mb}
            onChange={(e) => {
              set("max_file_mb", Number(e.target.value));
            }}
          />
          {source("max_file_mb")}
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("admin.settings.maxFiles")}
          <Input
            type="number"
            min={1}
            max={50}
            value={values.max_files_per_message}
            onChange={(e) => {
              set("max_files_per_message", Number(e.target.value));
            }}
          />
          {source("max_files_per_message")}
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("admin.settings.addressForm")}
        <select
          className="h-9 w-fit rounded-md border border-border bg-background px-2 text-sm"
          value={values.default_address_form}
          onChange={(e) => {
            set("default_address_form", e.target.value as (typeof FORMS)[number]);
          }}
        >
          {FORMS.map((f) => (
            <option key={f} value={f}>
              {t(`addressForm.${f}`)}
            </option>
          ))}
        </select>
        {source("default_address_form")}
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t("admin.settings.systemPrompt")}
        <textarea
          className={`${AREA} min-h-64 font-mono`}
          value={values.system_prompt}
          onChange={(e) => {
            set("system_prompt", e.target.value);
          }}
          data-testid="settings-system-prompt"
        />
        <span className="text-xs text-muted-foreground">
          {t("admin.settings.systemPromptHint")}
        </span>
        {source("system_prompt")}
      </label>

      {error && (
        <p role="alert" className="text-sm text-red-600" data-testid="settings-error">
          {error instanceof ApiError ? error.message : t("common.loadError")}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm text-green-700 dark:text-green-400">
          {t("admin.settings.saved")}
        </p>
      )}
      <Button type="submit" className="w-fit" disabled={save.isPending}>
        {t("admin.settings.save")}
      </Button>
    </form>
  );
}
