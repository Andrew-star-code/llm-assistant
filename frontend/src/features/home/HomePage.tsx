import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useChatModel, useSendMessage } from "@/features/chat/api";
import { Composer } from "@/features/composer/Composer";
import { NEW_CHAT_DRAFT, useDrafts } from "@/features/composer/drafts";
import { useMe } from "@/features/auth/useMe";
import { greetingKey } from "@/features/home/greeting";
import { useScenarios, useSelectedScenario } from "@/features/scenarios/api";
import { ScenarioCards } from "@/features/scenarios/ScenarioCards";

const EXAMPLES = [
  "home.examples.letter",
  "home.examples.summary",
  "home.examples.excel",
  "home.examples.explain",
];

// Стартовый экран §7.1: приветствие по имени и отчеству с учётом времени суток, карточки
// сценариев (§7.9) и примеры запросов. Чат создаётся первым сообщением — со сценарием, если выбран.
export function HomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const model = useChatModel();
  const send = useSendMessage();
  const setDraft = useDrafts((s) => s.setDraft);
  const [thinking, setThinking] = useState<boolean | null>(null);
  const scenarios = useScenarios();
  const selectedId = useSelectedScenario((s) => s.id);
  const select = useSelectedScenario((s) => s.select);
  const scenario = scenarios.data?.find((s) => s.id === selectedId) ?? null;
  const greeting = t(greetingKey(new Date()));
  const thinkingAvailable = scenario
    ? scenario.thinking_available
    : (model.data?.thinking_available ?? false);
  const thinkingValue =
    thinkingAvailable &&
    (thinking ?? (scenario ? scenario.thinking_default : model.data?.thinking_default) ?? false);
  const examples = scenario?.starter_prompts.length
    ? scenario.starter_prompts
    : EXAMPLES.map((key) => t(key));

  const submit = (content: string, attachmentIds: string[]) => {
    send.mutate(
      { chatId: null, content, thinking: thinkingValue, attachmentIds, scenarioId: scenario?.id },
      {
        onSuccess: ({ chatId }) => {
          select(null);
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
        thinkingAvailable={thinkingAvailable}
        thinking={thinkingValue}
        onThinkingChange={setThinking}
        onSend={submit}
        onStop={() => undefined}
        scenario={
          scenario
            ? {
                name: scenario.name,
                icon: scenario.icon,
                onReset: () => {
                  select(null);
                },
              }
            : null
        }
        attachmentRequired={
          scenario?.requires_attachment
            ? (scenario.attachment_hint ?? t("scenarios.attachFile"))
            : null
        }
      />
      {send.isError && (
        <p role="alert" className="text-sm text-red-600">
          {send.error.message}
        </p>
      )}
      <ScenarioCards scenarios={scenarios.data ?? []} selectedId={selectedId} onSelect={select} />
      <div className="grid gap-2 sm:grid-cols-2" data-testid="examples">
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              setDraft(NEW_CHAT_DRAFT, example);
            }}
            className="rounded-lg border border-border px-4 py-3 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {example}
          </button>
        ))}
      </div>
    </section>
  );
}
