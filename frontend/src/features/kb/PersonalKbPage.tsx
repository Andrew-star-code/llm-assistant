import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, unwrap } from "@/api/client";
import { useFileLimits } from "@/features/files/api";
import { DocumentTable } from "@/features/kb/DocumentTable";
import { hasPending, kbKeys, uploadDocument } from "@/features/kb/api";
import { UploadZone } from "@/features/kb/UploadZone";
import { formatBytes } from "@/lib/format";

/** «Моя база знаний» (§7.8): документы со статусами, загрузка, удаление, переиндексация, квота. */
export function PersonalKbPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const limits = useFileLimits();
  const [errors, setErrors] = useState<string[]>([]);
  const kb = useQuery({
    queryKey: kbKeys.personal,
    queryFn: async () => unwrap(await api.GET("/api/kb/personal")),
    // Пока документы индексируются — перечитываем статусы.
    refetchInterval: (query) => (hasPending(query.state.data?.documents) ? 2000 : false),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: kbKeys.personal });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const failed: string[] = [];
      for (const file of files) {
        try {
          await uploadDocument("/api/kb/personal/documents", file);
        } catch (error) {
          const reason = error instanceof ApiError && error.message ? error.message : "";
          failed.push(t("kb.uploadFailed", { name: file.name, reason }));
        }
        await refresh();
      }
      setErrors(failed);
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/kb/personal/documents/{document_id}", {
          params: { path: { document_id: id } },
        }),
      );
    },
    onSuccess: refresh,
  });
  const reindex = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/kb/personal/documents/{document_id}/reindex", {
          params: { path: { document_id: id } },
        }),
      ),
    onSuccess: refresh,
  });

  const quota = kb.data?.quota;
  // Без политики лимита квоты нет (null) — полоса пустая, подпись «без ограничения».
  const percent = quota?.max_bytes ? Math.min(100, (quota.used_bytes / quota.max_bytes) * 100) : 0;
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold">{t("kb.personalTitle")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("kb.personalHint")}</p>
      </div>
      {quota && (
        <div className="flex flex-col gap-1.5" data-testid="kb-quota">
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary" style={{ width: `${String(percent)}%` }} />
          </div>
          <span className="text-xs text-muted-foreground">
            {t("kb.quota", {
              used: formatBytes(quota.used_bytes),
              max: quota.max_bytes === null ? t("kb.unlimited") : formatBytes(quota.max_bytes),
              docs: quota.used_documents,
              maxDocs: quota.max_documents ?? t("kb.unlimited"),
            })}
          </span>
        </div>
      )}
      <UploadZone
        busy={upload.isPending}
        accept={limits.data?.accept.map((ext) => `.${ext}`).join(",")}
        onFiles={(files) => {
          if (files.length) upload.mutate(files);
        }}
      />
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-red-600" data-testid="kb-upload-errors">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {kb.isPending ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <DocumentTable
          documents={kb.data?.documents ?? []}
          onDelete={(doc) => {
            remove.mutate(doc.id);
          }}
          onReindex={(doc) => {
            reindex.mutate(doc.id);
          }}
        />
      )}
    </section>
  );
}
