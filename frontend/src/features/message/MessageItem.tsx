import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Info,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import type { FileEvent, SourceCard } from "@/api/sse";
import { useLiveAnswer, useMessageStream, type ToolStepView } from "@/features/chat/live";
import type { Message } from "@/features/chat/tree";
import type { Schemas } from "@/api/client";
import { FileCard, FileChip } from "@/features/files/FileCard";
import type { FileRef } from "@/features/files/fileRef";
import { Markdown } from "@/features/markdown/Markdown";
import { DislikeDialog } from "@/features/message/DislikeDialog";
import { ReasoningBlock } from "@/features/message/ReasoningBlock";
import { ToolSteps } from "@/features/message/ToolSteps";
import { SourceList } from "@/features/sources/SourceList";
import { SourceViewer } from "@/features/sources/SourceViewer";
import { useCopy } from "@/lib/useCopy";
import { cn } from "@/lib/utils";

export interface MessageActions {
  versions: Message[];
  onSelectVersion: (message: Message) => void;
  onRegenerate: (message: Message) => void;
  onFeedback: (
    message: Message,
    rating: 1 | -1 | null,
    reasons?: string[],
    comment?: string,
  ) => void;
  canRegenerate: boolean;
}

type MessageFile = Schemas["FileOut"];

function fromRest(file: MessageFile): FileRef {
  return { id: file.id, name: file.filename, size: file.size, hasPreview: file.has_preview };
}

function fromEvent(file: FileEvent): FileRef {
  return { id: file.file_id, name: file.name, size: file.size, hasPreview: file.preview };
}

const NO_SOURCES: SourceCard[] = [];

/** Источники, на которые ответ ссылается `[n]` (во время стрима — по уже пришедшему тексту). */
function citedSources(sources: SourceCard[], content: string): SourceCard[] {
  const cited = new Set(Array.from(content.matchAll(/\[(\d{1,2})\]/g), (m) => Number(m[1])));
  return sources.filter((s) => cited.has(s.index));
}

function stepsOf(message: Message): ToolStepView[] {
  return (message.tools ?? []).map((step) => ({
    callId: step.call_id,
    tool: step.tool,
    label: step.label,
    params: step.params ?? {},
    status: step.status,
  }));
}

function UserMessage({ message, highlighted }: { message: Message; highlighted: boolean }) {
  return (
    <div className="flex flex-col items-end gap-1.5" id={`message-${message.id}`}>
      {message.files && message.files.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
          {message.files.map((file) => (
            <FileChip key={file.id} file={fromRest(file)} />
          ))}
        </div>
      )}
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2.5 text-sm",
          highlighted && "ring-2 ring-primary",
        )}
        data-testid="user-message"
      >
        {message.content}
      </div>
    </div>
  );
}

function infoText(
  message: Message,
  t: (key: string, o?: Record<string, unknown>) => string,
): string {
  const parts = [];
  if (message.model) parts.push(t("message.info.model", { model: message.model }));
  if (message.latency_ms != null)
    parts.push(t("message.info.time", { seconds: (message.latency_ms / 1000).toFixed(1) }));
  if (message.completion_tokens != null)
    parts.push(
      t("message.info.tokens", {
        prompt: message.prompt_tokens ?? 0,
        completion: message.completion_tokens,
      }),
    );
  return parts.join(" · ");
}

function AssistantMessage({
  message,
  actions,
  highlighted,
}: {
  message: Message;
  actions: MessageActions;
  highlighted: boolean;
}) {
  const { t } = useTranslation();
  useMessageStream(message);
  const live = useLiveAnswer(message.id);
  const { copied, copy } = useCopy();
  const [dislikeOpen, setDislikeOpen] = useState(false);

  const streaming = message.status === "streaming";
  const content = streaming ? (live?.content ?? "") : message.content;
  const reasoning = streaming ? (live?.reasoning ?? "") : (message.reasoning ?? "");
  const reasoningMs = streaming ? live?.reasoningMs : message.reasoning_ms;
  const error = streaming ? live?.error : message.error;
  const steps = streaming ? (live?.tools ?? []) : stepsOf(message);
  const files = streaming
    ? (live?.files ?? []).map(fromEvent)
    : (message.files ?? []).map(fromRest);
  const allSources: SourceCard[] = (streaming ? live?.sources : message.sources) ?? NO_SOURCES;
  const sources = useMemo(() => citedSources(allSources, content), [allSources, content]);
  const citations = useMemo(() => new Set(allSources.map((s) => s.index)), [allSources]);
  const [openSource, setOpenSource] = useState<SourceCard | null>(null);
  const onCite = useCallback(
    (index: number) => {
      setOpenSource(allSources.find((s) => s.index === index) ?? null);
    },
    [allSources],
  );
  const index = actions.versions.findIndex((v) => v.id === message.id);
  const rating = message.feedback?.rating ?? null;

  return (
    <div
      className={cn("group/message", highlighted && "rounded-lg ring-2 ring-primary")}
      id={`message-${message.id}`}
    >
      {reasoning && <ReasoningBlock text={reasoning} ms={reasoningMs} streaming={streaming} />}
      <ToolSteps steps={steps} />
      <div data-testid="assistant-message" data-status={message.status}>
        {content ? (
          <Markdown text={content} streaming={streaming} citations={citations} onCite={onCite} />
        ) : streaming && !reasoning && !steps.length ? (
          <span className="inline-flex gap-1 py-2" aria-label={t("message.generating")}>
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60" />
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
          </span>
        ) : null}
      </div>

      <SourceList sources={sources} onOpen={setOpenSource} />
      {openSource && (
        <SourceViewer
          source={openSource}
          onClose={() => {
            setOpenSource(null);
          }}
        />
      )}
      {files.length > 0 && (
        <div className="mt-2 flex flex-col gap-2" data-testid="message-files">
          {files.map((file) => (
            <FileCard key={file.id} file={file} />
          ))}
        </div>
      )}

      {(message.status === "error" || message.status === "interrupted" || (streaming && error)) && (
        <div
          role="alert"
          className="mt-2 flex items-center gap-3 rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400"
        >
          <span className="flex-1">
            {message.status === "interrupted"
              ? t("message.interrupted")
              : t(`message.errors.${error?.code ?? "unknown"}`, {
                  defaultValue: error?.message ?? t("message.errors.unknown"),
                })}
          </span>
          {!streaming && actions.canRegenerate && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                actions.onRegenerate(message);
              }}
            >
              {t("message.retry")}
            </Button>
          )}
        </div>
      )}
      {message.status === "stopped" && (
        <p className="mt-1 text-xs text-muted-foreground">{t("message.stopped")}</p>
      )}

      {!streaming && (
        <div
          className="mt-1 flex items-center gap-0.5 text-muted-foreground"
          data-testid="message-actions"
        >
          {actions.versions.length > 1 && (
            <div className="mr-1 flex items-center text-xs" data-testid="version-switcher">
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={t("message.prevVersion")}
                disabled={index <= 0 || !actions.canRegenerate}
                onClick={() => {
                  const prev = actions.versions[index - 1];
                  if (prev) actions.onSelectVersion(prev);
                }}
              >
                <ChevronLeft className="size-4" />
              </Button>
              <span data-testid="version-label">
                {index + 1}/{actions.versions.length}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={t("message.nextVersion")}
                disabled={index >= actions.versions.length - 1 || !actions.canRegenerate}
                onClick={() => {
                  const next = actions.versions[index + 1];
                  if (next) actions.onSelectVersion(next);
                }}
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
          {content && (
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={t("message.copy")}
              title={t("message.copy")}
              onClick={() => {
                void copy(message.content);
              }}
            >
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={t("message.regenerate")}
            title={t("message.regenerate")}
            disabled={!actions.canRegenerate}
            onClick={() => {
              actions.onRegenerate(message);
            }}
          >
            <RefreshCw className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn("size-7", rating === 1 && "text-primary")}
            aria-label={t("message.like")}
            aria-pressed={rating === 1}
            onClick={() => {
              actions.onFeedback(message, rating === 1 ? null : 1);
            }}
          >
            <ThumbsUp className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn("size-7", rating === -1 && "text-primary")}
            aria-label={t("message.dislike")}
            aria-pressed={rating === -1}
            onClick={() => {
              if (rating === -1) actions.onFeedback(message, null);
              else setDislikeOpen(true);
            }}
          >
            <ThumbsDown className="size-4" />
          </Button>
          <span
            className="ml-1 inline-flex"
            title={infoText(message, t)}
            aria-label={infoText(message, t)}
          >
            <Info className="size-3.5 opacity-60" />
          </span>
        </div>
      )}
      {dislikeOpen && (
        <DislikeDialog
          onClose={() => {
            setDislikeOpen(false);
          }}
          onSubmit={(reasons, comment) => {
            actions.onFeedback(message, -1, reasons, comment);
            setDislikeOpen(false);
          }}
        />
      )}
    </div>
  );
}

export function MessageItem({
  message,
  actions,
  highlighted = false,
}: {
  message: Message;
  actions: MessageActions;
  highlighted?: boolean;
}) {
  return message.role === "user" ? (
    <UserMessage message={message} highlighted={highlighted} />
  ) : (
    <AssistantMessage message={message} actions={actions} highlighted={highlighted} />
  );
}
