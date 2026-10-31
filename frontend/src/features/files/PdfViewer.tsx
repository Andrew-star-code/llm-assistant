import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Document, Page, pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// Воркер pdf.js — из сборки приложения, без CDN (§4); eval выключен ради CSP.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
const OPTIONS = { isEvalSupported: false };

/** Просмотр PDF (оригинал или PDF-превью Office-файла): все страницы по ширине окна. */
export default function PdfViewer({ url }: { url: string }) {
  const { t } = useTranslation();
  const [pages, setPages] = useState(0);
  const [width, setWidth] = useState(800);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(200, Math.floor(entry.contentRect.width) - 32));
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={box} className="flex flex-col items-center gap-4 p-4" data-testid="pdf-viewer">
      <Document
        file={url}
        options={OPTIONS}
        loading={<p className="text-sm text-muted-foreground">{t("common.loading")}</p>}
        error={<p className="text-sm text-red-600">{t("files.previewError")}</p>}
        onLoadSuccess={({ numPages }) => {
          setPages(numPages);
        }}
      >
        {Array.from({ length: pages }, (_, index) => (
          <Page
            key={index}
            pageNumber={index + 1}
            width={width}
            renderTextLayer={false}
            renderAnnotationLayer={false}
            className="mb-4 shadow-md"
          />
        ))}
      </Document>
    </div>
  );
}
