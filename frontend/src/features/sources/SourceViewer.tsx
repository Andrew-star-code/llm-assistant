import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";

import { api, unwrap } from "@/api/client";
import type { SourceCard } from "@/api/sse";
import type { FileRef } from "@/features/files/fileRef";

const PreviewDialog = lazy(() => import("@/features/files/PreviewDialog"));

/**
 * Просмотр источника на нужной странице (§10.5). Документ базы знаний открывается через
 * `/api/kb/documents/{id}/…` — сервер заново проверяет права на базу; вложение — как файл чата.
 */
export function SourceViewer({ source, onClose }: { source: SourceCard; onClose: () => void }) {
  const documentId = source.kind === "kb" ? source.document_id : null;
  const fileId = source.kind === "attachment" ? source.file_id : null;
  const meta = useQuery({
    queryKey: ["source", documentId ?? fileId],
    queryFn: async (): Promise<FileRef> => {
      if (documentId) {
        const doc = unwrap(
          await api.GET("/api/kb/documents/{document_id}", {
            params: { path: { document_id: documentId } },
          }),
        );
        const base = `/api/kb/documents/${doc.id}`;
        return {
          id: doc.id,
          name: doc.filename,
          size: doc.size,
          hasPreview: doc.has_preview,
          urls: {
            download: `${base}/content`,
            inline: `${base}/content?download=false`,
            preview: `${base}/preview`,
          },
        };
      }
      const file = unwrap(
        await api.GET("/api/files/{file_id}", { params: { path: { file_id: fileId ?? "" } } }),
      );
      return { id: file.id, name: file.filename, size: file.size, hasPreview: file.has_preview };
    },
    enabled: Boolean(documentId ?? fileId),
    retry: false,
  });
  if (!meta.data) return null;
  return (
    <Suspense fallback={null}>
      <PreviewDialog file={meta.data} page={source.page ?? undefined} onClose={onClose} />
    </Suspense>
  );
}
