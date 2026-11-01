import { useQuery } from "@tanstack/react-query";

import { api, ApiError, csrfToken, unwrap, type Schemas } from "@/api/client";

export type FileOut = Schemas["FileOut"];
export type FileLimits = Schemas["FileLimits"];

export const fileKeys = {
  limits: ["files", "limits"] as const,
};

export function useFileLimits() {
  return useQuery({
    queryKey: fileKeys.limits,
    queryFn: async () => unwrap(await api.GET("/api/files/limits")),
    staleTime: 10 * 60_000,
  });
}

/**
 * Загрузка файла через XHR — ради прогресса (fetch не умеет прогресс отправки).
 * Ошибки сервера приходят в едином формате {"error": {"code", "message"}}.
 */
export function uploadFile(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<FileOut> {
  return csrfToken().then(
    (token) =>
      new Promise<FileOut>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/files");
        xhr.withCredentials = true;
        xhr.setRequestHeader("X-CSRF-Token", token);
        xhr.responseType = "json";
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(event.loaded / event.total);
        };
        xhr.onload = () => {
          const body = xhr.response as unknown;
          if (xhr.status === 201) {
            resolve(body as FileOut);
            return;
          }
          const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
          reject(
            new ApiError(
              xhr.status,
              error?.code ?? "upload_failed",
              error?.message ?? xhr.statusText,
            ),
          );
        };
        xhr.onerror = () => {
          reject(new ApiError(0, "network", ""));
        };
        xhr.onabort = () => {
          reject(new DOMException("aborted", "AbortError"));
        };
        signal?.addEventListener("abort", () => {
          xhr.abort();
        });
        const form = new FormData();
        form.append("file", file);
        xhr.send(form);
      }),
  );
}

export async function getFile(id: string): Promise<FileOut> {
  return unwrap(await api.GET("/api/files/{file_id}", { params: { path: { file_id: id } } }));
}

export async function deleteFile(id: string): Promise<void> {
  unwrap(await api.DELETE("/api/files/{file_id}", { params: { path: { file_id: id } } }));
}

export function downloadUrl(id: string): string {
  return `/api/files/${id}/content`;
}

export function inlineUrl(id: string): string {
  return `/api/files/${id}/content?download=false`;
}

export function previewUrl(id: string): string {
  return `/api/files/${id}/preview`;
}
