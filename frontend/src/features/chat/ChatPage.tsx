import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  stopMessage,
  useChat,
  useChatModel,
  useFeedback,
  useRegenerate,
  useSendMessage,
  useSetActiveLeaf,
  useUpdateChat,
} from "@/features/chat/api";
import { activeBranch, latestLeaf, siblings, type Message } from "@/features/chat/tree";
import { Composer } from "@/features/composer/Composer";
import { MessageItem, type MessageActions } from "@/features/message/MessageItem";

/** Страница чата (§7.1–7.4): лента активной ветки и поле ввода. */
export function ChatPage() {
  const { t } = useTranslation();
  const { chatId = "" } = useParams();
  const [params] = useSearchParams();
  const highlightId = params.get("m");
  const navigate = useNavigate();
  const chat = useChat(chatId);
  const model = useChatModel();
  const send = useSendMessage();
  const regenerate = useRegenerate(chatId);
  const setLeaf = useSetActiveLeaf(chatId);
  const updateChat = useUpdateChat();
  const feedback = useFeedback(chatId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  // Выбор «Размышлять» до ответа сервера — привязан к чату, чтобы не переносился в другой.
  const [override, setOverride] = useState<{ chatId: string; value: boolean } | null>(null);
  const thinkingOverride = override?.chatId === chatId ? override.value : null;

  const messages = useMemo(() => chat.data?.messages ?? [], [chat.data]);
  const branch = useMemo(
    () => activeBranch(messages, chat.data?.active_leaf_id),
    [messages, chat.data],
  );
  const streamingMessage = branch.find((m) => m.status === "streaming");
  const busy = Boolean(streamingMessage) || regenerate.isPending;
  const thinking =
    thinkingOverride ?? chat.data?.thinking_enabled ?? model.data?.thinking_default ?? false;

  // Автопрокрутка вниз, пока пользователь сам не прокрутил вверх.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current && !highlightId) el.scrollTop = el.scrollHeight;
  });

  // Переход из поиска к сообщению: переключаемся на ветку с ним и прокручиваем к нему.
  useEffect(() => {
    if (!highlightId || !messages.length) return;
    if (!branch.some((m) => m.id === highlightId) && messages.some((m) => m.id === highlightId)) {
      setLeaf.mutate(latestLeaf(messages, highlightId));
      return;
    }
    document.getElementById(`message-${highlightId}`)?.scrollIntoView({ block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightId, messages.length, branch.length]);

  // Esc — остановить генерацию (§7.10).
  useEffect(() => {
    if (!streamingMessage) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void stopMessage(streamingMessage.id);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [streamingMessage]);

  if (chat.isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
        <p>{t("chat.notFound")}</p>
        <button type="button" className="text-primary underline" onClick={() => void navigate("/")}>
          {t("sidebar.newChat")}
        </button>
      </div>
    );
  }

  const actions = (message: Message): MessageActions => ({
    versions: siblings(messages, message),
    canRegenerate: !busy,
    onSelectVersion: (version) => {
      setLeaf.mutate(latestLeaf(messages, version.id));
    },
    onRegenerate: (target) => {
      stickToBottom.current = true;
      regenerate.mutate({ messageId: target.id, thinking });
    },
    onFeedback: (target, rating, reasons, comment) => {
      feedback.mutate({
        messageId: target.id,
        feedback:
          rating === null
            ? null
            : { rating, reasons: (reasons ?? []) as never, comment: comment ?? null },
      });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto"
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6" data-testid="message-list">
          {chat.isPending && <p className="text-muted-foreground">{t("common.loading")}</p>}
          {branch.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              actions={actions(message)}
              highlighted={message.id === highlightId}
            />
          ))}
        </div>
      </div>
      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        <Composer
          draftKey={chatId}
          busy={busy}
          sending={send.isPending}
          thinkingAvailable={model.data?.thinking_available ?? false}
          thinking={thinking}
          onThinkingChange={(value) => {
            setOverride({ chatId, value });
            updateChat.mutate({ chatId, body: { thinking_enabled: value } });
          }}
          onSend={(content, attachmentIds) => {
            stickToBottom.current = true;
            send.mutate({ chatId, content, thinking, attachmentIds });
          }}
          onStop={() => {
            if (streamingMessage) void stopMessage(streamingMessage.id);
          }}
        />
        {send.isError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {send.error.message}
          </p>
        )}
      </div>
    </div>
  );
}
