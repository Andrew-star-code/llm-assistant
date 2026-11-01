import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { FileTypeIcon } from "@/features/files/FileCard";
import type { KbDocument } from "@/features/kb/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE: Record<KbDocument["status"], string> = {
  queued: "bg-muted text-muted-foreground",
  processing: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  ready: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  error: "bg-red-500/15 text-red-700 dark:text-red-400",
};

/** Документы базы со статусом индексации (§7.8, §13.2); общий для личной базы и админки. */
export function DocumentTable({
  documents,
  onDelete,
  onReindex,
}: {
  documents: KbDocument[];
  onDelete: (doc: KbDocument) => void;
  onReindex: (doc: KbDocument) => void;
}) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState<string | null>(null);
  if (!documents.length) {
    return <p className="py-6 text-center text-sm text-muted-foreground">{t("kb.empty")}</p>;
  }
  return (
    <ul
      className="divide-y divide-border rounded-lg border border-border"
      data-testid="kb-documents"
    >
      {documents.map((doc) => (
        <li
          key={doc.id}
          className="flex items-center gap-3 px-3 py-2.5 text-sm"
          data-testid="kb-document"
          data-status={doc.status}
        >
          <FileTypeIcon name={doc.filename} className="size-5 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium" title={doc.filename}>
              {doc.title}
            </div>
            <div className="truncate text-xs text-muted-foreground">
              {formatBytes(doc.size)} · {formatDateTime(doc.created_at)}
              {doc.status === "ready" ? ` · ${t("kb.chunks", { count: doc.chunks })}` : ""}
            </div>
            {doc.status === "error" && doc.error && (
              <div className="text-xs text-red-600" data-testid="kb-document-error">
                {doc.error}
              </div>
            )}
          </div>
          <span
            className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs", TONE[doc.status])}
            data-testid="kb-document-status"
          >
            {t(`kb.status.${doc.status}`)}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={t("kb.reindex")}
            title={t("kb.reindex")}
            disabled={doc.status === "queued" || doc.status === "processing"}
            onClick={() => {
              onReindex(doc);
            }}
          >
            <RefreshCw className="size-4" />
          </Button>
          {confirm === doc.id ? (
            <Button
              variant="outline"
              size="sm"
              className="text-red-600"
              onClick={() => {
                setConfirm(null);
                onDelete(doc);
              }}
            >
              {t("kb.confirmDelete")}
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              aria-label={t("kb.delete", { name: doc.title })}
              title={t("kb.delete", { name: doc.title })}
              onClick={() => {
                setConfirm(doc.id);
              }}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
