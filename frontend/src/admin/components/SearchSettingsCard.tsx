import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

type SearchSettings = Schemas["SearchSettingsOut"];

const QUERY_KEY = ["admin", "kb", "search-settings"] as const;

/** «Параметры поиска»: порог реранкера, подобранный на реальных документах (без перезапуска). */
export function SearchSettingsCard() {
  // «Сохранено» живёт в карточке: после сохранения форма пересоздаётся с новым значением.
  const [saved, setSaved] = useState(false);
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/admin/kb/search-settings")),
  });
  if (!settings.data) return null;
  // Новое сохранённое значение — новая форма с ним (без синхронизации состояния в эффекте).
  return (
    <SearchSettingsForm
      key={`${String(settings.data.score_threshold)}-${settings.data.updated_at ?? ""}`}
      initial={settings.data}
      saved={saved}
      onSavedChange={setSaved}
    />
  );
}

interface FormProps {
  initial: SearchSettings;
  saved: boolean;
  onSavedChange: (saved: boolean) => void;
}

function SearchSettingsForm({ initial, saved, onSavedChange }: FormProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(initial.score_threshold));
  const save = useMutation({
    mutationFn: async (threshold: number | null) =>
      unwrap(
        await api.PUT("/api/admin/kb/search-settings", { body: { score_threshold: threshold } }),
      ),
    onSuccess: (data) => {
      onSavedChange(true);
      queryClient.setQueryData(QUERY_KEY, data);
    },
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    save.mutate(Number(value.replace(",", ".")));
  };
  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
      data-testid="kb-search-settings"
    >
      <h2 className="font-medium">{t("admin.kb.search.title")}</h2>
      <p className="text-sm text-muted-foreground">{t("admin.kb.search.hint")}</p>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        {t("admin.kb.search.threshold")}
        <Input
          required
          type="number"
          min={0}
          max={1}
          step="any"
          className="w-28"
          value={value}
          onChange={(e) => {
            onSavedChange(false);
            setValue(e.target.value);
          }}
        />
      </label>
      <p className="text-xs text-muted-foreground" data-testid="kb-search-source">
        {initial.overridden && initial.updated_at
          ? t("admin.kb.search.overridden", {
              date: formatDateTime(initial.updated_at),
              value: initial.default_threshold,
            })
          : t("admin.kb.search.fromConfig")}
      </p>
      {save.isError && (
        <p role="alert" className="text-sm text-red-600">
          {save.error instanceof ApiError ? save.error.message : t("common.loadError")}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm text-green-700 dark:text-green-400">
          {t("admin.kb.search.saved")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" className="w-fit" disabled={save.isPending}>
          {t("admin.kb.search.save")}
        </Button>
        {initial.overridden && (
          <Button
            type="button"
            variant="outline"
            className="w-fit"
            disabled={save.isPending}
            onClick={() => {
              save.mutate(null);
            }}
          >
            {t("admin.kb.search.reset", { value: initial.default_threshold })}
          </Button>
        )}
      </div>
    </form>
  );
}
