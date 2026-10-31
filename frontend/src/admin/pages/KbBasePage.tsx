import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DocumentTable } from "@/features/kb/DocumentTable";
import { hasPending, kbKeys, uploadDocument } from "@/features/kb/api";
import { UploadZone } from "@/features/kb/UploadZone";
import { formatDateTime } from "@/lib/format";

const IMPORT_TONE = { scanning: "warn", running: "warn", done: "ok", error: "bad" } as const;

/** База знаний в админке: документы, загрузка, переиндексация, удаление, импорт из папки. */
export function KbBasePage() {
  const { t } = useTranslation();
  const { kbId = "" } = useParams();
  const queryClient = useQueryClient();
  const [errors, setErrors] = useState<string[]>([]);
  const base = useQuery({
    queryKey: kbKeys.admin,
    queryFn: async () => unwrap(await api.GET("/api/admin/kb")),
    select: (bases) => bases.find((b) => b.id === kbId),
  });
  const documents = useQuery({
    queryKey: [...kbKeys.adminBase(kbId), "documents"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/kb/{kb_id}/documents", { params: { path: { kb_id: kbId } } }),
      ),
    refetchInterval: (query) => (hasPending(query.state.data) ? 2000 : false),
  });
  const imports = useQuery({
    queryKey: [...kbKeys.adminBase(kbId), "imports"],
    queryFn: async () =>
      unwrap(await api.GET("/api/admin/kb/{kb_id}/imports", { params: { path: { kb_id: kbId } } })),
    refetchInterval: (query) =>
      query.state.data?.some((i) => i.status === "scanning" || i.status === "running")
        ? 2000
        : false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: kbKeys.adminBase(kbId) });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const failed: string[] = [];
      for (const file of files) {
        try {
          await uploadDocument(`/api/admin/kb/${kbId}/documents`, file);
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
        await api.DELETE("/api/admin/kb/{kb_id}/documents/{document_id}", {
          params: { path: { kb_id: kbId, document_id: id } },
        }),
      );
    },
    onSuccess: refresh,
  });
  const reindex = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/admin/kb/{kb_id}/documents/{document_id}/reindex", {
          params: { path: { kb_id: kbId, document_id: id } },
        }),
      ),
    onSuccess: refresh,
  });

  return (
    <section className="flex flex-col gap-5">
      <Link to="/admin/kb" className="flex w-fit items-center gap-1 text-sm text-muted-foreground">
        <ArrowLeft className="size-4" /> {t("admin.nav.kb")}
      </Link>
      <div>
        <h1 className="text-xl font-semibold" data-testid="kb-title">
          {base.data?.name ?? "…"}
        </h1>
        {base.data && (
          <p className="text-sm text-muted-foreground">
            {t(`admin.kb.levels.${base.data.level}`)}
            {base.data.roles.length > 0 && ` · ${base.data.roles.map((r) => r.name).join(", ")}`}
            {base.data.description && ` · ${base.data.description}`}
          </p>
        )}
      </div>
      <UploadZone
        busy={upload.isPending}
        onFiles={(files) => {
          if (files.length) upload.mutate(files);
        }}
      />
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-red-600">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <ImportPanel
        kbId={kbId}
        imports={imports.data ?? []}
        onStarted={() => {
          void refresh();
        }}
      />
      <h2 className="font-medium">{t("admin.kb.documents")}</h2>
      <DocumentTable
        documents={documents.data ?? []}
        onDelete={(doc) => {
          remove.mutate(doc.id);
        }}
        onReindex={(doc) => {
          reindex.mutate(doc.id);
        }}
      />
    </section>
  );
}

type ImportItem = Schemas["ImportOut"];

function ImportPanel({
  kbId,
  imports,
  onStarted,
}: {
  kbId: string;
  imports: ImportItem[];
  onStarted: () => void;
}) {
  const { t } = useTranslation();
  const [path, setPath] = useState("");
  const folders = useQuery({
    queryKey: ["admin", "kb", "import-folders"],
    queryFn: async () => unwrap(await api.GET("/api/admin/kb/import-folders")),
  });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/kb/{kb_id}/imports", {
          params: { path: { kb_id: kbId } },
          body: { path },
        }),
      ),
    onSuccess: onStarted,
  });
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
      data-testid="kb-import"
    >
      <h2 className="font-medium">{t("admin.kb.import")}</h2>
      <p className="text-xs text-muted-foreground">{t("admin.kb.importHint")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("admin.kb.importFolder")}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
          value={path}
          onChange={(e) => {
            setPath(e.target.value);
          }}
        >
          <option value="">{t("admin.kb.importFolder")}</option>
          {(folders.data ?? []).map((f) => (
            <option key={f.path} value={f.path}>
              {t("admin.kb.folderOption", { path: f.path, count: f.files })}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!path || start.isPending}
          onClick={() => {
            start.mutate();
          }}
        >
          {t("admin.kb.startImport")}
        </Button>
      </div>
      {start.isError && (
        <p role="alert" className="text-sm text-red-600">
          {start.error instanceof ApiError ? start.error.message : t("common.loadError")}
        </p>
      )}
      {imports.length > 0 && (
        <Table
          head={[
            t("admin.kb.importFolder"),
            t("admin.kb.importStatus"),
            t("admin.kb.progress"),
            t("admin.kb.created"),
          ]}
        >
          {imports.map((imp) => {
            const done = imp.documents.ready + imp.documents.error + imp.skipped;
            return (
              <tr key={imp.id} data-testid="kb-import-row" data-status={imp.status}>
                <Td>{imp.path}</Td>
                <Td>
                  <Badge tone={IMPORT_TONE[imp.status]}>
                    {t(`admin.kb.importStatuses.${imp.status}`)}
                  </Badge>
                  {imp.error && <div className="text-xs text-red-600">{imp.error}</div>}
                </Td>
                <Td>
                  {t("admin.kb.progressText", {
                    done,
                    total: imp.total,
                    ready: imp.documents.ready,
                    errors: imp.documents.error,
                    skipped: imp.skipped,
                  })}
                </Td>
                <Td>{formatDateTime(imp.created_at)}</Td>
              </tr>
            );
          })}
        </Table>
      )}
    </div>
  );
}
