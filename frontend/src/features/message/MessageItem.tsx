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
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useLiveAnswer, useMessageStream } from "@/features/chat/live";
import type { Message } from "@/features/chat/tree";
import { Markdown } from "@/features/markdown/Markdown";
import { DislikeDialog } from "@/features/message/DislikeDialog";
import { ReasoningBlock } from "@/features/message/ReasoningBlock";
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

function UserMessage({ message, highlighted }: { message: Message; highlighted: boolean }) {
  return (
    <div className="flex justify-end" id={`message-${message.id}`}>
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
  const index = actions.versions.findIndex((v) => v.id === message.id);
  const rating = message.feedback?.rating ?? null;

  return (
    <div
      className={cn("group/message", highlighted && "rounded-lg ring-2 ring-primary")}
      id={`message-${message.id}`}
    >
      {reasoning && <ReasoningBlock text={reasoning} ms={reasoningMs} streaming={streaming} />}
      <div data-testid="assistant-message" data-status={message.status}>
        {content ? (
          <Markdown text={content} streaming={streaming} />
        ) : streaming && !reasoning ? (
          <span className="inline-flex gap-1 py-2" aria-label={t("message.generating")}>
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60" />
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
            <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
          </span>
        ) : null}
      </div>

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
