import {
  Download,
  Eye,
  File as FileIcon,
  FileCode,
  FileSpreadsheet,
  FileText,
  Presentation,
} from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { downloadUrl } from "@/features/files/api";
import {
  canPreview,
  DOCUMENT_TYPES,
  PRESENTATION_TYPES,
  SPREADSHEET_TYPES,
  type FileRef,
} from "@/features/files/fileRef";
import { extensionOf, formatBytes } from "@/lib/format";

const PreviewDialog = lazy(() => import("@/features/files/PreviewDialog"));

export function FileTypeIcon({ name, className }: { name: string; className?: string }) {
  const ext = extensionOf(name);
  if (SPREADSHEET_TYPES.has(ext)) return <FileSpreadsheet className={className} />;
  if (PRESENTATION_TYPES.has(ext)) return <Presentation className={className} />;
  if (DOCUMENT_TYPES.has(ext)) return <FileText className={className} />;
  if (ext.length > 0 && ext.length <= 4) return <FileCode className={className} />;
  return <FileIcon className={className} />;
}

/** Карточка файла под ответом (§7.7): иконка формата, имя, размер, «Скачать», «Просмотр». */
export function FileCard({ file }: { file: FileRef }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div
      className="flex w-full max-w-sm items-center gap-3 rounded-lg border border-border bg-background px-3 py-2"
      data-testid="file-card"
    >
      <FileTypeIcon name={file.name} className="size-8 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium" title={file.name} data-testid="file-name">
          {file.name}
        </div>
        <div className="text-xs text-muted-foreground">{formatBytes(file.size)}</div>
      </div>
      {canPreview(file) && (
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={t("files.preview")}
          title={t("files.preview")}
          onClick={() => {
            setOpen(true);
          }}
        >
          <Eye className="size-4" />
        </Button>
      )}
      <a
        href={downloadUrl(file.id)}
        download={file.name}
        aria-label={t("files.download")}
        title={t("files.download")}
        className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Download className="size-4" />
      </a>
      {open && (
        <Suspense fallback={null}>
          <PreviewDialog
            file={file}
            onClose={() => {
              setOpen(false);
            }}
          />
        </Suspense>
      )}
    </div>
  );
}

/** Чип вложения в сообщении пользователя: имя и размер, по клику — просмотр. */
export function FileChip({ file }: { file: FileRef }) {
  const [open, setOpen] = useState(false);
  const previewable = canPreview(file);
  const body = (
    <>
      <FileTypeIcon name={file.name} className="size-4 shrink-0" />
      <span className="max-w-48 truncate">{file.name}</span>
      <span className="text-muted-foreground">{formatBytes(file.size)}</span>
    </>
  );
  return (
    <>
      {previewable ? (
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted"
          data-testid="message-file-chip"
          onClick={() => {
            setOpen(true);
          }}
        >
          {body}
        </button>
      ) : (
        <a
          href={downloadUrl(file.id)}
          download={file.name}
          className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted"
          data-testid="message-file-chip"
        >
          {body}
        </a>
      )}
      {open && (
        <Suspense fallback={null}>
          <PreviewDialog
            file={file}
            onClose={() => {
              setOpen(false);
            }}
          />
        </Suspense>
      )}
    </>
  );
}
