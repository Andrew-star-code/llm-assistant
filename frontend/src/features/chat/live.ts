import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { create } from "zustand";

import { subscribeMessageStream, type FileEvent, type SourceCard } from "@/api/sse";
import { chatKeys, invalidateChatLists, type ChatDetail } from "@/features/chat/api";
import { LIMITS_QUERY_KEY } from "@/features/limits/api";
import type { Message } from "@/features/chat/tree";

/** Шаг инструмента в ленте ответа (§7.4): живой из SSE или из истории (`MessageOut.tools`). */
export interface ToolStepView {
  callId: string;
  tool: string;
  label: string;
  params: Record<string, string>;
  status: "running" | "ok" | "error" | "timeout";
}

/** Живое состояние ответа, который сейчас стримится (§7.4, §8.5). */
export interface LiveAnswer {
  tools: ToolStepView[];
  files: FileEvent[];
  sources: SourceCard[];
  content: string;
  reasoning: string;
  reasoningStartedAt: number | null;
  reasoningMs: number | null;
  error: { code: string; message: string } | null;
}

interface LiveState {
  answers: Record<string, LiveAnswer>;
  update: (id: string, patch: (prev: LiveAnswer) => Partial<LiveAnswer>) => void;
  clear: (id: string) => void;
}

const EMPTY: LiveAnswer = {
  tools: [],
  files: [],
  sources: [],
  content: "",
  reasoning: "",
  reasoningStartedAt: null,
  reasoningMs: null,
  error: null,
};

export const useLiveStore = create<LiveState>((set) => ({
  answers: {},
  update: (id, patch) => {
    set((state) => {
      const prev = state.answers[id] ?? EMPTY;
      return { answers: { ...state.answers, [id]: { ...prev, ...patch(prev) } } };
    });
  },
  clear: (id) => {
    set((state) => {
      const { [id]: _removed, ...rest } = state.answers;
      return { answers: rest };
    });
  },
}));

export function useLiveAnswer(id: string): LiveAnswer | undefined {
  return useLiveStore((s) => s.answers[id]);
}

/**
 * Подписка на поток ответа, пока он в статусе streaming. По `message.end` перечитываем чат —
 * финальное состояние берётся из БД (там же токены, время, статус).
 */
export function useMessageStream(message: Message): void {
  const queryClient = useQueryClient();
  const { update, clear } = useLiveStore.getState();
  const streaming = message.status === "streaming";
  const { id, chat_id: chatId } = message;
  const wasStreaming = useRef(streaming);

  // Ответ мог завершиться раньше, чем пришёл message.end (например, чат перечитали по REST):
  // переход streaming → финальный статус обновляет историю независимо от SSE.
  useEffect(() => {
    if (wasStreaming.current && !streaming) {
      clear(id);
      void invalidateChatLists(queryClient);
    }
    wasStreaming.current = streaming;
  }, [streaming, id, queryClient, clear]);

  useEffect(() => {
    if (!streaming) return;
    clear(id);
    const unsubscribe = subscribeMessageStream(id, {
      onReasoning: (text) => {
        update(id, (prev) => ({
          reasoning: prev.reasoning + text,
          reasoningStartedAt: prev.reasoningStartedAt ?? Date.now(),
        }));
      },
      onContent: (text) => {
        update(id, (prev) => ({
          content: prev.content + text,
          reasoningMs:
            prev.reasoningMs ??
            (prev.reasoningStartedAt ? Date.now() - prev.reasoningStartedAt : null),
        }));
      },
      onToolStart: ({ call_id: callId, tool, label, params }) => {
        update(id, (prev) => ({
          tools: [...prev.tools, { callId, tool, label, params, status: "running" }],
        }));
      },
      onToolEnd: ({ call_id: callId, tool, label, status, params }) => {
        update(id, (prev) => {
          const step: ToolStepView = { callId, tool, label, params, status };
          const exists = prev.tools.some((s) => s.callId === callId);
          return {
            tools: exists
              ? prev.tools.map((s) => (s.callId === callId ? step : s))
              : [...prev.tools, step],
          };
        });
      },
      onSources: (sources) => {
        update(id, () => ({ sources }));
      },
      onFile: (file) => {
        update(id, (prev) => ({ files: [...prev.files, file] }));
      },
      onError: (error) => {
        update(id, () => ({ error }));
      },
      onLimits: (limits) => {
        queryClient.setQueryData(LIMITS_QUERY_KEY, limits);
      },
      onTitle: ({ title }) => {
        queryClient.setQueryData<ChatDetail>(chatKeys.detail(chatId), (chat) =>
          chat ? { ...chat, title } : chat,
        );
        void invalidateChatLists(queryClient);
      },
      onEnd: () => {
        void queryClient.invalidateQueries({ queryKey: chatKeys.detail(chatId) }).then(() => {
          clear(id);
        });
        void invalidateChatLists(queryClient);
      },
      onFatal: () => {
        void queryClient.invalidateQueries({ queryKey: chatKeys.detail(chatId) });
      },
    });
    return unsubscribe;
  }, [streaming, id, chatId, queryClient, update, clear]);
}
