import { BookOpen, Paperclip } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SourceCard } from "@/api/sse";

/** Карточки источников под ответом (§10.5): только те, на которые модель сослалась. */
export function SourceList({
  sources,
  onOpen,
}: {
  sources: SourceCard[];
  onOpen: (source: SourceCard) => void;
}) {
  const { t } = useTranslation();
  if (!sources.length) return null;
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2" data-testid="sources">
      {sources.map((s) => (
        <button
          key={s.index}
          type="button"
          onClick={() => {
            onOpen(s);
          }}
          className="flex gap-2 rounded-lg border border-border bg-background p-2.5 text-left text-sm transition-colors hover:bg-muted"
          data-testid="source-card"
          title={t("sources.open")}
        >
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
            {s.index}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 font-medium">
              {s.kind === "kb" ? (
                <BookOpen className="size-3.5 shrink-0" aria-hidden />
              ) : (
                <Paperclip className="size-3.5 shrink-0" aria-hidden />
              )}
              <span className="truncate" data-testid="source-title">
                {s.title}
              </span>
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              {[
                s.kind === "kb" ? s.kb_name : t("sources.attachment"),
                s.page ? t("sources.page", { page: s.page }) : null,
                s.section,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            <span className="mt-1 line-clamp-2 text-xs text-muted-foreground">{s.snippet}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
