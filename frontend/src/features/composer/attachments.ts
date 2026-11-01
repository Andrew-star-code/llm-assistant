import { create } from "zustand";

import { ApiError } from "@/api/client";
import {
  deleteFile,
  getFile,
  uploadFile,
  type FileLimits,
  type FileOut,
} from "@/features/files/api";
import { extensionOf } from "@/lib/format";

/**
 * Вложения поля ввода (§7.3): файл загружается сразу при выборе, чип показывает прогресс,
 * статус разбора и ошибку. Списки — по ключу черновика, чтобы у каждого чата были свои.
 */
export type AttachmentStatus = "uploading" | "processing" | "ready" | "error";

export interface PendingAttachment {
  key: string;
  name: string;
  size: number;
  progress: number;
  status: AttachmentStatus;
  error: string | null;
  file: FileOut | null;
}

export type RejectReason = "tooMany" | "tooLarge" | "unsupported";

interface AttachmentsState {
  lists: Record<string, PendingAttachment[]>;
  patch: (draftKey: string, key: string, patch: Partial<PendingAttachment>) => void;
  push: (draftKey: string, item: PendingAttachment) => void;
  remove: (draftKey: string, key: string) => void;
  clear: (draftKey: string) => void;
}

const EMPTY: PendingAttachment[] = [];
const POLL_MS = 1000;
const controllers = new Map<string, AbortController>();

export const useAttachments = create<AttachmentsState>((set) => ({
  lists: {},
  patch: (draftKey, key, patch) => {
    set((state) => {
      const list = state.lists[draftKey];
      if (!list) return state;
      return {
        lists: {
          ...state.lists,
          [draftKey]: list.map((item) => (item.key === key ? { ...item, ...patch } : item)),
        },
      };
    });
  },
  push: (draftKey, item) => {
    set((state) => ({
      lists: { ...state.lists, [draftKey]: [...(state.lists[draftKey] ?? []), item] },
    }));
  },
  remove: (draftKey, key) => {
    set((state) => ({
      lists: {
        ...state.lists,
        [draftKey]: (state.lists[draftKey] ?? []).filter((item) => item.key !== key),
      },
    }));
  },
  clear: (draftKey) => {
    set((state) => {
      const { [draftKey]: _removed, ...rest } = state.lists;
      return { lists: rest };
    });
  },
}));

export function useAttachmentList(draftKey: string): PendingAttachment[] {
  return useAttachments((s) => s.lists[draftKey] ?? EMPTY);
}

/** Что отправлять: id прочитанных файлов; `pending` — ещё идёт загрузка или разбор. */
export function attachmentSummary(list: PendingAttachment[]): { ids: string[]; pending: boolean } {
  return {
    ids: list.flatMap((item) => (item.status === "ready" && item.file ? [item.file.id] : [])),
    pending: list.some((item) => item.status === "uploading" || item.status === "processing"),
  };
}

function statusOf(file: FileOut): AttachmentStatus {
  if (file.parse_status === "ready") return "ready";
  if (file.parse_status === "error") return "error";
  return "processing";
}

async function pollUntilParsed(draftKey: string, key: string, file: FileOut): Promise<void> {
  let current = file;
  const { patch } = useAttachments.getState();
  while (statusOf(current) === "processing") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    // Чип удалили, пока файл разбирался, — опрос больше не нужен.
    if (!useAttachments.getState().lists[draftKey]?.some((item) => item.key === key)) return;
    try {
      current = await getFile(current.id);
    } catch {
      continue;
    }
  }
  patch(draftKey, key, {
    file: current,
    status: statusOf(current),
    error: current.parse_error ?? null,
  });
}

let sequence = 0;

/** Проверки на клиенте — только для быстрого ответа; окончательно решает сервер. */
export function checkFile(
  file: File,
  limits: FileLimits | undefined,
  count: number,
): RejectReason | null {
  if (!limits) return null;
  if (count >= limits.max_files_per_message) return "tooMany";
  if (file.size > limits.max_file_mb * 1024 * 1024) return "tooLarge";
  const ext = extensionOf(file.name);
  const name = file.name.toLowerCase();
  if (!limits.accept.includes(ext) && !limits.accept.includes(name)) return "unsupported";
  return null;
}

export function addFiles(
  draftKey: string,
  files: File[],
  limits: FileLimits | undefined,
  rejectText: (reason: RejectReason) => string,
): void {
  const { push, patch } = useAttachments.getState();
  for (const file of files) {
    sequence += 1;
    const key = `a${String(sequence)}`;
    const count = (useAttachments.getState().lists[draftKey] ?? EMPTY).filter(
      (item) => item.status !== "error",
    ).length;
    const reason = checkFile(file, limits, count);
    push(draftKey, {
      key,
      name: file.name,
      size: file.size,
      progress: 0,
      status: reason ? "error" : "uploading",
      error: reason ? rejectText(reason) : null,
      file: null,
    });
    if (reason) continue;
    const controller = new AbortController();
    controllers.set(key, controller);
    uploadFile(
      file,
      (progress) => {
        patch(draftKey, key, { progress });
      },
      controller.signal,
    )
      .then((uploaded) => {
        patch(draftKey, key, {
          file: uploaded,
          progress: 1,
          status: statusOf(uploaded),
          error: uploaded.parse_error ?? null,
        });
        return pollUntilParsed(draftKey, key, uploaded);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        patch(draftKey, key, {
          status: "error",
          error: error instanceof ApiError && error.message ? error.message : null,
        });
      })
      .finally(() => {
        controllers.delete(key);
      });
  }
}

/** Крестик на чипе: отменить загрузку и удалить файл на сервере, если он ещё не отправлен. */
export function removeAttachment(draftKey: string, item: PendingAttachment): void {
  controllers.get(item.key)?.abort();
  useAttachments.getState().remove(draftKey, item.key);
  if (item.file) void deleteFile(item.file.id).catch(() => undefined);
}
