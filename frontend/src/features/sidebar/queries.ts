import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import { chatKeys, invalidateChatLists } from "@/features/chat/api";

const PAGE = 100;

/** Чаты без папки и не закреплённые — постранично (курсор), для групп по датам. */
export function useChatPages() {
  return useInfiniteQuery({
    queryKey: chatKeys.list({ pinned: false }),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/chats", {
          params: { query: { pinned: false, cursor: pageParam, limit: PAGE } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function usePinnedChats() {
  return useQuery({
    queryKey: chatKeys.list({ pinned: true }),
    queryFn: async () =>
      unwrap(await api.GET("/api/chats", { params: { query: { pinned: true, limit: 200 } } })),
  });
}

export function useFolderChats(folderId: string, enabled: boolean) {
  return useQuery({
    queryKey: chatKeys.list({ folderId }),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/chats", { params: { query: { folder_id: folderId, limit: 200 } } }),
      ),
  });
}

export function useFolders() {
  return useQuery({
    queryKey: chatKeys.folders,
    queryFn: async () => unwrap(await api.GET("/api/folders")),
  });
}

export function useFolderMutations() {
  const queryClient = useQueryClient();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: chatKeys.folders });
    await invalidateChatLists(queryClient);
  };
  return {
    create: useMutation({
      mutationFn: async (name: string) =>
        unwrap(await api.POST("/api/folders", { body: { name } })),
      onSuccess: refresh,
    }),
    rename: useMutation({
      mutationFn: async (input: { id: string; name: string }) =>
        unwrap(
          await api.PATCH("/api/folders/{folder_id}", {
            params: { path: { folder_id: input.id } },
            body: { name: input.name },
          }),
        ),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: async (input: { id: string; chats: "move" | "delete" }) => {
        unwrap(
          await api.DELETE("/api/folders/{folder_id}", {
            params: { path: { folder_id: input.id }, query: { chats: input.chats } },
          }),
        );
      },
      onSuccess: refresh,
    }),
  };
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: ["chats", "search", query],
    enabled: query.length > 0,
    queryFn: async () =>
      unwrap(await api.GET("/api/chats/search", { params: { query: { q: query } } })),
    staleTime: 10_000,
  });
}
