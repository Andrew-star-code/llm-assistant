import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, SquarePen } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { ChatListItem } from "@/features/chat/api";
import { ChatItem } from "@/features/sidebar/ChatItem";
import { groupByDate, type DateGroup } from "@/features/sidebar/dateGroups";
import { FolderSection, RootDropZone } from "@/features/sidebar/FolderSection";
import { useChatPages, useFolders, usePinnedChats } from "@/features/sidebar/queries";

type Row =
  | { kind: "header"; key: string; label: string }
  | { kind: "chat"; key: string; chat: ChatListItem };

const MONTHS = new Intl.DateTimeFormat("ru-RU", { month: "long" });

function groupLabel(group: DateGroup, t: (key: string) => string): string {
  switch (group.kind) {
    case "monthOfYear": {
      const name = MONTHS.format(new Date(2000, group.month, 1));
      return name.charAt(0).toUpperCase() + name.slice(1);
    }
    case "year":
      return String(group.year);
    default:
      return t(`sidebar.groups.${group.kind}`);
  }
}

/**
 * История чатов (§7.2): «Новый чат», поиск, папки, закреплённые, группы по датам.
 * Список виртуализирован и подгружается курсором — 5000 чатов без подтормаживаний.
 */
export function ChatSidebar({ onSearch }: { onSearch: () => void }) {
  const { t } = useTranslation();
  const pages = useChatPages();
  const pinned = usePinnedChats();
  const folders = useFolders();
  const scrollRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const folderList = useMemo(() => folders.data ?? [], [folders.data]);

  const rows = useMemo<Row[]>(() => {
    const result: Row[] = [];
    const pinnedItems = pinned.data?.items ?? [];
    if (pinnedItems.length) {
      result.push({ kind: "header", key: "h-pinned", label: t("sidebar.groups.pinned") });
      pinnedItems.forEach((chat) => result.push({ kind: "chat", key: chat.id, chat }));
    }
    const loose = (pages.data?.pages.flatMap((p) => p.items) ?? []).filter((c) => !c.folder_id);
    for (const { group, items } of groupByDate(loose, (c) => c.last_message_at)) {
      result.push({
        kind: "header",
        key: `h-${JSON.stringify(group)}`,
        label: groupLabel(group, t),
      });
      items.forEach((chat) => result.push({ kind: "chat", key: chat.id, chat }));
    }
    return result;
  }, [pages.data, pinned.data, t]);

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual управляет состоянием сам
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => (rows[index]?.kind === "header" ? 30 : 34),
    overscan: 12,
    scrollMargin: listRef.current?.offsetTop ?? 0,
  });
  const items = virtualizer.getVirtualItems();
  const lastIndex = items[items.length - 1]?.index ?? 0;

  useEffect(() => {
    if (lastIndex >= rows.length - 15 && pages.hasNextPage && !pages.isFetchingNextPage) {
      void pages.fetchNextPage();
    }
  }, [lastIndex, rows.length, pages]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-1 p-2">
        <Link
          to="/"
          className="flex items-center gap-2 rounded-md px-2 py-2 text-sm font-medium hover:bg-muted"
          data-testid="new-chat"
        >
          <SquarePen className="size-4" />
          {t("sidebar.newChat")}
          <kbd className="ml-auto text-[10px] text-muted-foreground">Ctrl+Shift+O</kbd>
        </Link>
        <button
          type="button"
          onClick={onSearch}
          className="flex items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-muted"
          data-testid="open-search"
        >
          <Search className="size-4" />
          {t("sidebar.search")}
          <kbd className="ml-auto text-[10px] text-muted-foreground">Ctrl+K</kbd>
        </button>
      </div>
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto px-2 pb-2"
        data-testid="chat-history"
      >
        <FolderSection folders={folderList} />
        <RootDropZone>
          <div
            ref={listRef}
            className="relative mt-2"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {items.map((item) => {
              const row = rows[item.index];
              if (!row) return null;
              return (
                <div
                  key={row.key}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  // Строка с открытым меню — поверх соседей: transform создаёт свой контекст наложения.
                  className="absolute left-0 top-0 w-full has-[[role=menu]]:z-20"
                  style={{
                    transform: `translateY(${item.start - virtualizer.options.scrollMargin}px)`,
                  }}
                >
                  {row.kind === "header" ? (
                    <div className="px-2 pb-1 pt-3 text-xs font-medium text-muted-foreground">
                      {row.label}
                    </div>
                  ) : (
                    <ChatItem chat={row.chat} folders={folderList} />
                  )}
                </div>
              );
            })}
          </div>
          {rows.length === 0 && !pages.isPending && (
            <p className="px-2 py-2 text-sm text-muted-foreground">{t("sidebar.emptyHistory")}</p>
          )}
        </RootDropZone>
      </div>
    </div>
  );
}
