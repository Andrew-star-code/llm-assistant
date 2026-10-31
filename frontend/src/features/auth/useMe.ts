import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "@/api/client";

export type Me = Schemas["Me"];

export const ME_QUERY_KEY = ["auth", "me"] as const;

/** Текущий пользователь; null — не вошёл (401). */
export async function fetchMe(): Promise<Me | null> {
  const { data, response } = await api.GET("/api/auth/me");
  if (response.status === 401) return null;
  if (!data) throw new Error(`GET /api/auth/me: ${response.status}`);
  return data;
}

export function useMe() {
  return useQuery({ queryKey: ME_QUERY_KEY, queryFn: fetchMe, staleTime: 60_000 });
}

export function useSetMe() {
  const queryClient = useQueryClient();
  return (me: Me | null) => {
    queryClient.setQueryData(ME_QUERY_KEY, me);
  };
}

export function hasPermission(me: Me | null | undefined, permission: string): boolean {
  return Boolean(me?.permissions.includes(permission));
}
