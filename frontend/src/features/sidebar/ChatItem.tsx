import { FolderInput, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useNavigate } from "react-router";

import type { Schemas } from "@/api/client";
import { useDeleteChat, useUpdateChat, type ChatListItem } from "@/features/chat/api";
import { cn } from "@/lib/utils";

export const CHAT_DRAG_TYPE = "application/x-ai-assistant-chat";

const MENU_ITEM =
  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted";

/** Строка чата в истории: переход, перетаскивание в папку, меню действий (§7.2). */
export function ChatItem({
  chat,
  folders,
}: {
  chat: ChatListItem;
  folders: Schemas["FolderOut"][];
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const update = useUpdateChat();
  const remove = useDeleteChat();
  const [menu, setMenu] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(chat.title ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setMenu(false);
        setConfirmDelete(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [menu]);

  const saveTitle = () => {
    setRenaming(false);
    const value = title.trim();
    if (value && value !== chat.title) update.mutate({ chatId: chat.id, body: { title: value } });
  };
  const onRenameKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") saveTitle();
    if (event.key === "Escape") {
      setTitle(chat.title ?? "");
      setRenaming(false);
    }
  };

  if (renaming) {
    return (
      <input
        autoFocus
        value={title}
        aria-label={t("sidebar.rename")}
        onChange={(e) => {
          setTitle(e.target.value);
        }}
        onBlur={saveTitle}
        onKeyDown={onRenameKey}
        className="h-8 w-full rounded-md border border-primary bg-background px-2 text-sm outline-none"
      />
    );
  }

  return (
    <div ref={ref} className="group/chat relative" data-testid="chat-item">
      <NavLink
        to={`/c/${chat.id}`}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(CHAT_DRAG_TYPE, chat.id);
          e.dataTransfer.effectAllowed = "move";
        }}
        className={({ isActive }) =>
          cn(
            "block truncate rounded-md py-1.5 pl-2 pr-8 text-sm hover:bg-muted",
            isActive && "bg-muted font-medium",
          )
        }
      >
        {chat.title ?? t("chat.newChatTitle")}
      </NavLink>
      <button
        type="button"
        aria-label={t("sidebar.chatMenu")}
        aria-haspopup="menu"
        aria-expanded={menu}
        onClick={() => {
          setMenu(!menu);
        }}
        className="absolute right-1 top-1 rounded p-1 text-muted-foreground opacity-0 hover:bg-background group-hover/chat:opacity-100 focus:opacity-100 aria-expanded:opacity-100"
      >
        <MoreHorizontal className="size-4" />
      </button>
      {menu && (
        <div
          role="menu"
          className="absolute right-0 top-8 z-30 w-56 rounded-lg border border-border bg-background p-1 shadow-lg"
        >
          <button
            role="menuitem"
            type="button"
            className={MENU_ITEM}
            onClick={() => {
              setMenu(false);
              setRenaming(true);
            }}
          >
            <Pencil className="size-4" /> {t("sidebar.rename")}
          </button>
          <button
            role="menuitem"
            type="button"
            className={MENU_ITEM}
            onClick={() => {
              setMenu(false);
              update.mutate({ chatId: chat.id, body: { pinned: !chat.pinned } });
            }}
          >
            {chat.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
            {chat.pinned ? t("sidebar.unpin") : t("sidebar.pin")}
          </button>
          {(folders.length > 0 || chat.folder_id) && (
            <label className={cn(MENU_ITEM, "cursor-default")}>
              <FolderInput className="size-4 shrink-0" />
              <select
                aria-label={t("sidebar.moveToFolder")}
                className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                value={chat.folder_id ?? ""}
                onChange={(e) => {
                  setMenu(false);
                  update.mutate({ chatId: chat.id, body: { folder_id: e.target.value || null } });
                }}
              >
                <option value="">{t("sidebar.noFolder")}</option>
                {folders.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {confirmDelete ? (
            <button
              role="menuitem"
              type="button"
              className={cn(MENU_ITEM, "text-red-600")}
              onClick={() => {
                setMenu(false);
                // Не mutate(…, {onSuccess}): после удаления список перечитывается и этот пункт
                // размонтируется раньше — колбэк мутации тогда не вызывается.
                void remove
                  .mutateAsync(chat.id)
                  .then(() => navigate("/"))
                  .catch(() => undefined);
              }}
            >
              <Trash2 className="size-4" /> {t("sidebar.confirmDelete")}
            </button>
          ) : (
            <button
              role="menuitem"
              type="button"
              className={cn(MENU_ITEM, "text-red-600")}
              onClick={() => {
                setConfirmDelete(true);
              }}
            >
              <Trash2 className="size-4" /> {t("sidebar.delete")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
