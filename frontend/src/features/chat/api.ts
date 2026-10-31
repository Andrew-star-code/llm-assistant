import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/api/client";
import type { Message } from "@/features/chat/tree";

export type ChatDetail = Schemas["ChatDetail"];
export type ChatListItem = Schemas["ChatListItem"];

export const chatKeys = {
  all: ["chats"] as const,
  list: (params: { pinned?: boolean; folderId?: string }) => ["chats", "list", params] as const,
  detail: (id: string) => ["chat", id] as const,
  folders: ["folders"] as const,
  model: ["models", "chat"] as const,
};

export function useChat(chatId: string | undefined) {
  return useQuery({
    queryKey: chatKeys.detail(chatId ?? ""),
    enabled: Boolean(chatId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/chats/{chat_id}", { params: { path: { chat_id: chatId ?? "" } } }),
      ),
  });
}

export function useChatModel() {
  return useQuery({
    queryKey: chatKeys.model,
    queryFn: async () => unwrap(await api.GET("/api/models/chat")),
    staleTime: 5 * 60_000,
  });
}

/** Добавляет/заменяет сообщения в кэше чата и выставляет активный лист. */
export function upsertMessages(
  queryClient: QueryClient,
  chatId: string,
  messages: Message[],
  activeLeafId?: string,
): void {
  queryClient.setQueryData<ChatDetail>(chatKeys.detail(chatId), (chat) => {
    if (!chat) return chat;
    const byId = new Map(chat.messages.map((m) => [m.id, m]));
    for (const message of messages) byId.set(message.id, message);
    return {
      ...chat,
      messages: [...byId.values()],
      active_leaf_id: activeLeafId ?? chat.active_leaf_id,
    };
  });
}

export function invalidateChatLists(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: chatKeys.all });
}

export async function createChat(thinking: boolean | null): Promise<ChatDetail> {
  return unwrap(await api.POST("/api/chats", { body: { thinking_enabled: thinking } }));
}

/** Отправка сообщения: при необходимости создаёт чат; возвращает id чата. */
export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      chatId: string | null;
      content: string;
      thinking: boolean | null;
      attachmentIds?: string[];
    }) => {
      let chatId = input.chatId;
      if (!chatId) {
        const chat = await createChat(input.thinking);
        queryClient.setQueryData(chatKeys.detail(chat.id), chat);
        chatId = chat.id;
      }
      const result = unwrap(
        await api.POST("/api/chats/{chat_id}/messages", {
          params: { path: { chat_id: chatId } },
          body: {
            content: input.content,
            thinking: input.thinking,
            attachment_ids: input.attachmentIds ?? [],
          },
        }),
      );
      upsertMessages(
        queryClient,
        chatId,
        [result.user_message, result.assistant_message],
        result.assistant_message.id,
      );
      return { chatId, ...result };
    },
    onSuccess: () => invalidateChatLists(queryClient),
  });
}

export function useRegenerate(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { messageId: string; thinking: boolean | null }) =>
      unwrap(
        await api.POST("/api/messages/{message_id}/regenerate", {
          params: { path: { message_id: input.messageId } },
          body: { thinking: input.thinking },
        }),
      ),
    onSuccess: (message) => {
      upsertMessages(queryClient, chatId, [message], message.id);
    },
  });
}

export async function stopMessage(messageId: string): Promise<void> {
  unwrap(
    await api.POST("/api/messages/{message_id}/stop", {
      params: { path: { message_id: messageId } },
    }),
  );
}

export function useSetActiveLeaf(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (leafId: string) => {
      queryClient.setQueryData<ChatDetail>(chatKeys.detail(chatId), (chat) =>
        chat ? { ...chat, active_leaf_id: leafId } : chat,
      );
      return unwrap(
        await api.PATCH("/api/chats/{chat_id}", {
          params: { path: { chat_id: chatId } },
          body: { active_leaf_id: leafId },
        }),
      );
    },
  });
}

export function useUpdateChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { chatId: string; body: Schemas["ChatUpdate"] }) =>
      unwrap(
        await api.PATCH("/api/chats/{chat_id}", {
          params: { path: { chat_id: input.chatId } },
          body: input.body,
        }),
      ),
    onSuccess: async (_, input) => {
      await invalidateChatLists(queryClient);
      await queryClient.invalidateQueries({ queryKey: chatKeys.detail(input.chatId) });
    },
  });
}

export function useDeleteChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (chatId: string) => {
      unwrap(await api.DELETE("/api/chats/{chat_id}", { params: { path: { chat_id: chatId } } }));
    },
    onSuccess: async (_, chatId) => {
      queryClient.removeQueries({ queryKey: chatKeys.detail(chatId) });
      await invalidateChatLists(queryClient);
    },
  });
}

export function useFeedback(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { messageId: string; feedback: Schemas["FeedbackIn"] | null }) => {
      const path = { params: { path: { message_id: input.messageId } } };
      if (input.feedback === null) {
        await api.DELETE("/api/messages/{message_id}/feedback", path);
        return null;
      }
      return unwrap(
        await api.PUT("/api/messages/{message_id}/feedback", { ...path, body: input.feedback }),
      );
    },
    onSuccess: (feedback, input) => {
      queryClient.setQueryData<ChatDetail>(chatKeys.detail(chatId), (chat) =>
        chat
          ? {
              ...chat,
              messages: chat.messages.map((m) =>
                m.id === input.messageId ? { ...m, feedback } : m,
              ),
            }
          : chat,
      );
    },
  });
}
