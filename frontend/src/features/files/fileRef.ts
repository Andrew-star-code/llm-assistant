import { extensionOf } from "@/lib/format";

/** Минимум, который нужен карточке: из REST (FileOut) или из события SSE `file`. */
export interface FileRef {
  id: string;
  name: string;
  size: number;
  hasPreview: boolean;
}

export const SPREADSHEET_TYPES = new Set(["xlsx", "xls", "ods", "csv", "tsv"]);
export const PRESENTATION_TYPES = new Set(["pptx", "ppt", "odp"]);
export const DOCUMENT_TYPES = new Set(["docx", "doc", "odt", "rtf", "pdf", "md", "txt"]);
// Отрисовываются в браузере без PDF-превью (§7.7).
export const TEXT_PREVIEW = new Set([
  "md",
  "markdown",
  "csv",
  "tsv",
  "txt",
  "log",
  "json",
  "xml",
  "yaml",
  "yml",
]);

export function canPreview(file: FileRef): boolean {
  const ext = extensionOf(file.name);
  return file.hasPreview || ext === "pdf" || TEXT_PREVIEW.has(ext);
}
