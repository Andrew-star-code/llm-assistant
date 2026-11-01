import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** Черновики поля ввода по чатам (§7.3): сохраняются при переключении чатов и перезагрузке. */
interface DraftState {
  drafts: Record<string, string>;
  setDraft: (key: string, text: string) => void;
}

export const NEW_CHAT_DRAFT = "new";

export const useDrafts = create<DraftState>()(
  persist(
    (set) => ({
      drafts: {},
      setDraft: (key, text) => {
        set((state) => {
          const { [key]: _previous, ...rest } = state.drafts;
          return { drafts: text ? { ...rest, [key]: text } : rest };
        });
      },
    }),
    { name: "ai-assistant.drafts", storage: createJSONStorage(() => localStorage), version: 1 },
  ),
);
