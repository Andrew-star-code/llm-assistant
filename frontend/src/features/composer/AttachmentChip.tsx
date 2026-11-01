import { Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PendingAttachment } from "@/features/composer/attachments";
import { FileTypeIcon } from "@/features/files/FileCard";
import { cn } from "@/lib/utils";

/** Чип файла в поле ввода (§7.3): прогресс загрузки, «читаю…», «готово», «ошибка: причина». */
export function AttachmentChip({
  item,
  onRemove,
}: {
  item: PendingAttachment;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const status =
    item.status === "uploading"
      ? t("composer.attachments.uploading", { percent: Math.round(item.progress * 100) })
      : item.status === "processing"
        ? t("composer.attachments.processing")
        : item.status === "ready"
          ? t("composer.attachments.ready")
          : t("composer.attachments.error", {
              reason: item.error ?? t("composer.attachments.unknownError"),
            });
  return (
    <div
      className={cn(
        "relative flex max-w-72 items-center gap-2 overflow-hidden rounded-lg border px-2 py-1.5 text-xs",
        item.status === "error"
          ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400"
          : "border-border bg-muted/50",
      )}
      data-testid="attachment-chip"
      data-status={item.status}
      title={`${item.name} — ${status}`}
    >
      {item.status === "uploading" || item.status === "processing" ? (
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
      ) : (
        <FileTypeIcon name={item.name} className="size-4 shrink-0" />
      )}
      <div className="min-w-0">
        <div className="truncate font-medium">{item.name}</div>
        <div className="truncate opacity-80" data-testid="attachment-status">
          {status}
        </div>
      </div>
      <button
        type="button"
        className="ml-1 rounded p-0.5 hover:bg-black/10 dark:hover:bg-white/10"
        aria-label={t("composer.attachments.remove", { name: item.name })}
        onClick={onRemove}
      >
        <X className="size-3.5" />
      </button>
      {item.status === "uploading" && (
        <div
          className="absolute bottom-0 left-0 h-0.5 bg-primary transition-[width]"
          style={{ width: `${String(Math.round(item.progress * 100))}%` }}
        />
      )}
    </div>
  );
}
