import { useQuery } from "@tanstack/react-query";
import { Download, X } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { downloadUrl, inlineUrl, previewUrl } from "@/features/files/api";
import { parseDelimited } from "@/features/files/delimited";
import { TEXT_PREVIEW, type FileRef } from "@/features/files/fileRef";
import { Markdown } from "@/features/markdown/Markdown";
import { extensionOf } from "@/lib/format";

const PdfViewer = lazy(() => import("@/features/files/PdfViewer"));

function TextPreview({ file }: { file: FileRef }) {
  const { t } = useTranslation();
  const ext = extensionOf(file.name);
  const query = useQuery({
    queryKey: ["file-text", file.id],
    queryFn: async () => {
      const url = file.urls?.inline ?? inlineUrl(file.id);
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      return (await response.text()).replace(/^\uFEFF/, "");
    },
  });
  if (query.isPending)
    return <p className="p-4 text-sm text-muted-foreground">{t("common.loading")}</p>;
  if (query.isError) return <p className="p-4 text-sm text-red-600">{t("files.previewError")}</p>;
  if (ext === "md" || ext === "markdown")
    return (
      <div className="p-6">
        <Markdown text={query.data} />
      </div>
    );
  if (ext === "csv" || ext === "tsv") {
    const [head, ...rows] = parseDelimited(query.data, ext);
    return (
      <div className="overflow-auto p-4">
        <table className="w-full border-collapse text-sm" data-testid="csv-preview">
          <thead>
            <tr>
              {head?.map((cell, i) => (
                <th
                  key={i}
                  className="border border-border bg-muted px-2 py-1 text-left font-semibold"
                >
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, i) => (
                  <td key={i} className="border border-border px-2 py-1">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <pre className="whitespace-pre-wrap p-4 font-mono text-xs">{query.data}</pre>;
}

/** Просмотр файла (§7.7): PDF и PDF-превью — pdf.js; Markdown, CSV и текст — отрисованными. */
export default function PreviewDialog({
  file,
  page,
  onClose,
}: {
  file: FileRef;
  /** Открыть PDF на этой странице (источник цитаты, §10.5). */
  page?: number;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const ext = extensionOf(file.name);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  let body;
  const urls = file.urls ?? {
    download: downloadUrl(file.id),
    inline: inlineUrl(file.id),
    preview: previewUrl(file.id),
  };
  if (ext === "pdf") body = <PdfViewer url={urls.inline} page={page} />;
  else if (file.hasPreview) body = <PdfViewer url={urls.preview} page={page} />;
  else if (TEXT_PREVIEW.has(ext)) body = <TextPreview file={file} />;
  else body = <p className="p-4 text-sm text-muted-foreground">{t("files.noPreview")}</p>;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-2 sm:p-6"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={file.name}
        data-testid="preview-dialog"
        className="flex h-full w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl"
        onMouseDown={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{file.name}</h2>
          <a
            href={urls.download}
            download={file.name}
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm hover:bg-muted"
          >
            <Download className="size-4" />
            {t("files.download")}
          </a>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={t("files.close")}
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-muted/40">
          <Suspense
            fallback={<p className="p-4 text-sm text-muted-foreground">{t("common.loading")}</p>}
          >
            {body}
          </Suspense>
        </div>
      </div>
    </div>
  );
}
