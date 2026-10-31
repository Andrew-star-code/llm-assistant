import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useChatModel, useSendMessage } from "@/features/chat/api";
import { Composer } from "@/features/composer/Composer";
import { NEW_CHAT_DRAFT, useDrafts } from "@/features/composer/drafts";
import { useMe } from "@/features/auth/useMe";
import { greetingKey } from "@/features/home/greeting";

const EXAMPLES = [
  "home.examples.letter",
  "home.examples.summary",
  "home.examples.excel",
  "home.examples.explain",
];

// Стартовый экран §7.1: приветствие по имени и отчеству с учётом времени суток,
// примеры запросов; карточки сценариев — этап 5. Чат создаётся первым сообщением.
export function HomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const model = useChatModel();
  const send = useSendMessage();
  const setDraft = useDrafts((s) => s.setDraft);
  const [thinking, setThinking] = useState<boolean | null>(null);
  const greeting = t(greetingKey(new Date()));
  const thinkingValue = thinking ?? model.data?.thinking_default ?? false;

  const submit = (content: string, attachmentIds: string[]) => {
    send.mutate(
      { chatId: null, content, thinking: thinkingValue, attachmentIds },
      {
        onSuccess: ({ chatId }) => {
          void navigate(`/c/${chatId}`);
        },
      },
    );
  };

  return (
    <section className="mx-auto flex h-full max-w-3xl flex-col justify-center gap-8 px-4 py-10">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight" data-testid="greeting">
          {me?.address
            ? t("home.greetingWithName", { greeting, name: me.address })
            : `${greeting}!`}
        </h1>
        <p className="text-muted-foreground">{t("home.subtitle")}</p>
      </div>
      <Composer
        draftKey={NEW_CHAT_DRAFT}
        busy={false}
        sending={send.isPending}
        thinkingAvailable={model.data?.thinking_available ?? false}
        thinking={thinkingValue}
        onThinkingChange={setThinking}
        onSend={submit}
        onStop={() => undefined}
      />
      {send.isError && (
        <p role="alert" className="text-sm text-red-600">
          {send.error.message}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        {EXAMPLES.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setDraft(NEW_CHAT_DRAFT, t(key));
            }}
            className="rounded-lg border border-border px-4 py-3 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {t(key)}
          </button>
        ))}
      </div>
    </section>
  );
}
