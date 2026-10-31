import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";

import { api, unwrap, type Schemas } from "@/api/client";

export type ScenarioCard = Schemas["ScenarioCard"];

export const scenarioKeys = {
  list: ["scenarios"] as const,
  admin: ["admin", "scenarios"] as const,
  options: ["admin", "scenarios", "options"] as const,
};

/** Сценарии, доступные ролям пользователя (§7.9); список строит сервер. */
export function useScenarios() {
  return useQuery({
    queryKey: scenarioKeys.list,
    queryFn: async () => unwrap(await api.GET("/api/scenarios")),
    staleTime: 60_000,
  });
}

/** Сценарий, выбранный на стартовом экране до первого сообщения. */
export const useSelectedScenario = create<{
  id: string | null;
  select: (id: string | null) => void;
}>((set) => ({
  id: null,
  select: (id) => {
    set({ id });
  },
}));
