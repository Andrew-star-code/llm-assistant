import { ApiError, csrfToken, type Schemas } from "@/api/client";

export type KbDocument = Schemas["DocumentOut"];
export type PersonalKb = Schemas["PersonalKbOut"];

export const kbKeys = {
  personal: ["kb", "personal"] as const,
  admin: ["admin", "kb"] as const,
  adminBase: (id: string) => ["admin", "kb", id] as const,
};

/** Идёт ли ещё индексация — пока да, список перечитывается. */
export function hasPending(docs: KbDocument[] | undefined): boolean {
  return Boolean(docs?.some((d) => d.status === "queued" || d.status === "processing"));
}

/** Загрузка документа (multipart) с CSRF; ошибка — ApiError с текстом сервера. */
export async function uploadDocument(url: string, file: File): Promise<KbDocument> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(url, {
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
  return body as KbDocument;
}
