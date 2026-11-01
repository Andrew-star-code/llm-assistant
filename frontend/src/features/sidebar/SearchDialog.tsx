import { Search } from "lucide-react";
import { useDeferredValue, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useSearch } from "@/features/sidebar/queries";
import { cn } from "@/lib/utils";

/** Поиск по чатам (Ctrl+K, §7.2): названия и текст сообщений, подсветка, переход к сообщению. */
export function SearchDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query.trim());
  const search = useSearch(deferred);
  // Выделенный результат сбрасывается при новом запросе: индекс привязан к тексту запроса.
  const [selection, setSelection] = useState({ query: "", index: 0 });
  const active = selection.query === deferred ? selection.index : 0;
  const setActive = (update: number | ((i: number) => number)) => {
    setSelection({
      query: deferred,
      index: typeof update === "function" ? update(active) : update,
    });
  };
  const hits = search.data ?? [];

  const open = (index: number) => {
    const hit = hits[index];
    if (!hit) return;
    onClose();
    void navigate(`/c/${hit.chat_id}${hit.message_id ? `?m=${hit.message_id}` : ""}`);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") onClose();
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, hits.length - 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    }
    if (event.key === "Enter") open(active);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("search.title")}
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        onMouseDown={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search className="size-4 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            onKeyDown={onKeyDown}
            placeholder={t("search.placeholder")}
            aria-label={t("search.placeholder")}
            className="h-12 flex-1 bg-transparent text-sm outline-none"
            data-testid="search-input"
          />
        </div>
        <ul
          className="max-h-[50vh] overflow-y-auto p-1"
          role="listbox"
          aria-label={t("search.results")}
        >
          {hits.map((hit, index) => (
            <li key={hit.chat_id} role="option" aria-selected={index === active}>
              <button
                type="button"
                onMouseEnter={() => {
                  setActive(index);
                }}
                onClick={() => {
                  open(index);
                }}
                className={cn(
                  "w-full rounded-md px-3 py-2 text-left",
                  index === active && "bg-muted",
                )}
                data-testid="search-hit"
              >
                <div className="truncate text-sm font-medium">
                  {hit.chat_title ?? t("chat.newChatTitle")}
                </div>
                <div className="line-clamp-2 text-xs text-muted-foreground">
                  {hit.fragments.map((fragment, i) =>
                    fragment.match ? (
                      <mark
                        key={i}
                        className="rounded bg-amber-200 px-0.5 text-foreground dark:bg-amber-500/40"
                      >
                        {fragment.text}
                      </mark>
                    ) : (
                      <span key={i}>{fragment.text}</span>
                    ),
                  )}
                </div>
              </button>
            </li>
          ))}
          {deferred && search.isSuccess && hits.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              {t("common.nothingFound")}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
