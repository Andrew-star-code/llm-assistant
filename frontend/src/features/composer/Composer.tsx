import { ArrowUp, Brain, Paperclip, Square } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  addFiles,
  attachmentSummary,
  removeAttachment,
  useAttachmentList,
  useAttachments,
  type RejectReason,
} from "@/features/composer/attachments";
import { AttachmentChip } from "@/features/composer/AttachmentChip";
import { useDrafts } from "@/features/composer/drafts";
import { ScenarioBadge } from "@/features/scenarios/ScenarioBadge";
import { useFileLimits } from "@/features/files/api";
import { blockingItem, useMyLimits } from "@/features/limits/api";
import { LimitNote } from "@/features/limits/LimitNote";
import { cn } from "@/lib/utils";

export interface ComposerProps {
  draftKey: string;
  busy: boolean;
  sending: boolean;
  thinkingAvailable: boolean;
  thinking: boolean;
  onThinkingChange: (value: boolean) => void;
  onSend: (text: string, attachmentIds: string[]) => void;
  onStop: () => void;
  autoFocus?: boolean;
  /** Активный сценарий (§7.3): индикатор и кнопка сброса. */
  scenario?: { name: string; icon: string | null; onReset?: () => void } | null;
  /** Сценарий требует вложение, а в чате его ещё нет: текст подсказки («Приложите договор»). */
  attachmentRequired?: string | null;
}

const MAX_HEIGHT = 240;

/** Поле ввода (§7.3): Enter — отправить, Shift+Enter — новая строка, «Стоп» во время генерации. */
export function Composer({
  draftKey,
  busy,
  sending,
  thinkingAvailable,
  thinking,
  onThinkingChange,
  onSend,
  onStop,
  autoFocus = true,
  scenario = null,
  attachmentRequired = null,
}: ComposerProps) {
  const { t } = useTranslation();
  const text = useDrafts((s) => s.drafts[draftKey] ?? "");
  const setDraft = useDrafts((s) => s.setDraft);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const limits = useFileLimits();
  const attachments = useAttachmentList(draftKey);
  const { ids, pending } = attachmentSummary(attachments);
  const clearAttachments = useAttachments((s) => s.clear);
  const myLimits = useMyLimits();
  // Лимит, действующий на все сообщения, исчерпан — поле закрыто до сброса (§12.4).
  const blocked = blockingItem(myLimits.data) !== null;

  const rejectText = (reason: RejectReason) =>
    t(`composer.attachments.${reason}`, {
      max: reason === "tooMany" ? limits.data?.max_files_per_message : limits.data?.max_file_mb,
    });
  const attach = (files: File[]) => {
    if (files.length) addFiles(draftKey, files, limits.data, rejectText);
  };

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus, draftKey]);

  // Отправка ждёт окончания загрузки и разбора файлов (§7.3); файлы с ошибкой не отправляются.
  const needsFile = Boolean(attachmentRequired) && ids.length === 0;
  const submit = () => {
    const value = text.trim();
    if (!value || busy || sending || pending || needsFile || blocked) return;
    onSend(value, ids);
    setDraft(draftKey, "");
    clearAttachments(draftKey);
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files);
    if (files.length) {
      event.preventDefault();
      attach(files);
    }
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDragging(true);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDragging(false);
    attach(Array.from(event.dataTransfer.files));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div
      className={cn(
        "relative rounded-xl border border-border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring",
        dragging && "ring-2 ring-primary",
      )}
      data-testid="composer"
      onDragOver={onDragOver}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-primary/10 text-sm font-medium text-primary">
          {t("composer.dropHere")}
        </div>
      )}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-1 pb-2" data-testid="attachment-chips">
          {attachments.map((item) => (
            <AttachmentChip
              key={item.key}
              item={item}
              onRemove={() => {
                removeAttachment(draftKey, item);
              }}
            />
          ))}
        </div>
      )}
      {needsFile && (
        <p className="px-2 pb-1 text-xs text-primary" data-testid="attachment-required">
          {attachmentRequired}
        </p>
      )}
      <textarea
        ref={ref}
        rows={1}
        value={text}
        aria-label={t("composer.placeholder")}
        placeholder={t("composer.placeholder")}
        data-testid="composer-input"
        onChange={(e) => {
          setDraft(draftKey, e.target.value);
        }}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        disabled={blocked}
        className="max-h-60 w-full resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            data-testid="file-input"
            accept={limits.data?.accept.map((ext) => `.${ext}`).join(",")}
            onChange={(event) => {
              attach(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground"
            aria-label={t("composer.attach")}
            title={t("composer.attachHint", {
              mb: limits.data?.max_file_mb ?? 50,
              count: limits.data?.max_files_per_message ?? 10,
            })}
            data-testid="attach-button"
            onClick={() => fileInput.current?.click()}
          >
            <Paperclip className="size-4" />
          </Button>
          {scenario && (
            <ScenarioBadge name={scenario.name} icon={scenario.icon} onReset={scenario.onReset} />
          )}
          {thinkingAvailable && (
            <button
              type="button"
              aria-pressed={thinking}
              data-testid="thinking-toggle"
              onClick={() => {
                onThinkingChange(!thinking);
              }}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                thinking
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <Brain className="size-3.5" />
              {t("composer.thinking")}
            </button>
          )}
        </div>
        {busy ? (
          <Button
            size="icon"
            variant="outline"
            onClick={onStop}
            aria-label={t("composer.stop")}
            data-testid="stop-button"
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={submit}
            disabled={!text.trim() || sending || pending || needsFile || blocked}
            aria-label={t("composer.send")}
            title={
              pending
                ? t("composer.attachments.waiting")
                : needsFile
                  ? (attachmentRequired ?? undefined)
                  : undefined
            }
            data-testid="send-button"
          >
            <ArrowUp />
          </Button>
        )}
      </div>
      <LimitNote limits={myLimits.data} />
    </div>
  );
}
