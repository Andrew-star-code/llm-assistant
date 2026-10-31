import { ArrowUp, Brain, Square } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useDrafts } from "@/features/composer/drafts";
import { cn } from "@/lib/utils";

export interface ComposerProps {
  draftKey: string;
  busy: boolean;
  sending: boolean;
  thinkingAvailable: boolean;
  thinking: boolean;
  onThinkingChange: (value: boolean) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  autoFocus?: boolean;
}

const MAX_HEIGHT = 240;

/** Поле ввода (§7.3): Enter — отправить, Shift+Enter — новая строка, «Стоп» во время генерации. */
export function Composer({
  draftKey,
  busy,
  sending,
  thinkingAvailable,
  thinking,
  onThinkingChange,
  onSend,
  onStop,
  autoFocus = true,
}: ComposerProps) {
  const { t } = useTranslation();
  const text = useDrafts((s) => s.drafts[draftKey] ?? "");
  const setDraft = useDrafts((s) => s.setDraft);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus, draftKey]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy || sending) return;
    onSend(value);
    setDraft(draftKey, "");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="rounded-xl border border-border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring">
      <textarea
        ref={ref}
        rows={1}
        value={text}
        aria-label={t("composer.placeholder")}
        placeholder={t("composer.placeholder")}
        data-testid="composer-input"
        onChange={(e) => {
          setDraft(draftKey, e.target.value);
        }}
        onKeyDown={onKeyDown}
        className="max-h-60 w-full resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between gap-2 px-1">
        <div>
          {thinkingAvailable && (
            <button
              type="button"
              aria-pressed={thinking}
              data-testid="thinking-toggle"
              onClick={() => {
                onThinkingChange(!thinking);
              }}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                thinking
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <Brain className="size-3.5" />
              {t("composer.thinking")}
            </button>
          )}
        </div>
        {busy ? (
          <Button
            size="icon"
            variant="outline"
            onClick={onStop}
            aria-label={t("composer.stop")}
            data-testid="stop-button"
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={submit}
            disabled={!text.trim() || sending}
            aria-label={t("composer.send")}
            data-testid="send-button"
          >
            <ArrowUp />
          </Button>
        )}
      </div>
    </div>
  );
}
