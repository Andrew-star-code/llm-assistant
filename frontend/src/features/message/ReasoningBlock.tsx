import { Brain, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Блок «Размышления»: свёрнут по умолчанию, показывает время; во время генерации — живой текст. */
export function ReasoningBlock({
  text,
  ms,
  streaming,
}: {
  text: string;
  ms: number | null | undefined;
  streaming: boolean;
}) {
  const { t } = useTranslation();
  const seconds = ms != null ? Math.max(1, Math.round(ms / 1000)) : null;
  const label =
    streaming && ms == null
      ? t("message.thinkingNow")
      : seconds
        ? t("message.thoughtFor", { seconds })
        : t("message.reasoning");
  return (
    <details
      className="group mb-3 rounded-lg border border-border bg-muted/30 text-sm"
      data-testid="reasoning"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
        <Brain className={streaming && ms == null ? "size-4 animate-pulse" : "size-4"} />
        {label}
      </summary>
      <div className="whitespace-pre-wrap border-t border-border px-3 py-2 text-muted-foreground">
        {text}
      </div>
    </details>
  );
}
