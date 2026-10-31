import { ChevronRight, Folder, FolderPlus, Pencil, Trash2 } from "lucide-react";
import { useState, type DragEvent, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { useUpdateChat } from "@/features/chat/api";
import { CHAT_DRAG_TYPE, ChatItem } from "@/features/sidebar/ChatItem";
import { useFolderChats, useFolderMutations } from "@/features/sidebar/queries";
import { cn } from "@/lib/utils";

type FolderOut = Schemas["FolderOut"];

function useDropChat(folderId: string | null) {
  const update = useUpdateChat();
  const [over, setOver] = useState(false);
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (e.dataTransfer.types.includes(CHAT_DRAG_TYPE)) {
          e.preventDefault();
          setOver(true);
        }
      },
      onDragLeave: () => {
        setOver(false);
      },
      onDrop: (e: DragEvent) => {
        setOver(false);
        const chatId = e.dataTransfer.getData(CHAT_DRAG_TYPE);
        if (chatId) update.mutate({ chatId, body: { folder_id: folderId } });
      },
    },
  };
}

/** Зона «без папки»: перетащить чат сюда — убрать из папки. */
export function RootDropZone({ children }: { children: React.ReactNode }) {
  const drop = useDropChat(null);
  return (
    <div {...drop.props} className={cn(drop.over && "rounded-md bg-primary/5 ring-1 ring-primary")}>
      {children}
    </div>
  );
}

function FolderRow({ folder, folders }: { folder: FolderOut; folders: FolderOut[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(folder.name);
  const [deleting, setDeleting] = useState(false);
  const chats = useFolderChats(folder.id, open);
  const { rename, remove } = useFolderMutations();
  const drop = useDropChat(folder.id);

  return (
    <div
      {...drop.props}
      className={cn("rounded-md", drop.over && "bg-primary/5 ring-1 ring-primary")}
      data-testid="folder"
    >
      <div className="group/folder flex items-center gap-1 rounded-md px-1 hover:bg-muted">
        <button
          type="button"
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left text-sm"
          onClick={() => {
            setOpen(!open);
          }}
        >
          <ChevronRight
            className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")}
          />
          <Folder className="size-4 shrink-0 text-muted-foreground" />
          {renaming ? (
            <input
              autoFocus
              value={name}
              aria-label={t("sidebar.renameFolder")}
              onClick={(e) => {
                e.stopPropagation();
              }}
              onChange={(e) => {
                setName(e.target.value);
              }}
              onBlur={() => {
                setRenaming(false);
                if (name.trim() && name !== folder.name)
                  rename.mutate({ id: folder.id, name: name.trim() });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  setName(folder.name);
                  setRenaming(false);
                }
              }}
              className="min-w-0 flex-1 rounded border border-primary bg-background px-1 outline-none"
            />
          ) : (
            <span className="truncate">{folder.name}</span>
          )}
        </button>
        <button
          type="button"
          aria-label={t("sidebar.renameFolder")}
          className="rounded p-1 text-muted-foreground opacity-0 group-hover/folder:opacity-100"
          onClick={() => {
            setRenaming(true);
          }}
        >
          <Pencil className="size-3.5" />
        </button>
        <button
          type="button"
          aria-label={t("sidebar.deleteFolder")}
          className="rounded p-1 text-muted-foreground opacity-0 group-hover/folder:opacity-100"
          onClick={() => {
            setDeleting(!deleting);
          }}
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
      {deleting && (
        <div className="mx-2 my-1 flex flex-col gap-1 rounded-md border border-border p-2 text-xs">
          <span>{t("sidebar.deleteFolderQuestion")}</span>
          <button
            type="button"
            className="rounded px-2 py-1 text-left hover:bg-muted"
            onClick={() => {
              remove.mutate({ id: folder.id, chats: "move" });
            }}
          >
            {t("sidebar.deleteFolderMove")}
          </button>
          <button
            type="button"
            className="rounded px-2 py-1 text-left text-red-600 hover:bg-muted"
            onClick={() => {
              remove.mutate({ id: folder.id, chats: "delete" });
            }}
          >
            {t("sidebar.deleteFolderWithChats")}
          </button>
        </div>
      )}
      {open && (
        <div className="ml-4 border-l border-border pl-1">
          {chats.data?.items.map((chat) => (
            <ChatItem key={chat.id} chat={chat} folders={folders} />
          ))}
          {chats.data?.items.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">{t("sidebar.emptyFolder")}</p>
          )}
        </div>
      )}
    </div>
  );
}

export function FolderSection({ folders }: { folders: FolderOut[] }) {
  const { t } = useTranslation();
  const { create } = useFolderMutations();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const submit = (e: SubmitEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate(name.trim());
    setName("");
    setAdding(false);
  };
  return (
    <section className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between px-2 pt-2 text-xs font-medium text-muted-foreground">
        {t("sidebar.folders")}
        <button
          type="button"
          aria-label={t("sidebar.newFolder")}
          title={t("sidebar.newFolder")}
          className="rounded p-1 hover:bg-muted"
          onClick={() => {
            setAdding(true);
          }}
        >
          <FolderPlus className="size-3.5" />
        </button>
      </div>
      {adding && (
        <form onSubmit={submit} className="px-1">
          <input
            autoFocus
            value={name}
            placeholder={t("sidebar.folderName")}
            aria-label={t("sidebar.folderName")}
            onChange={(e) => {
              setName(e.target.value);
            }}
            onBlur={() => {
              setAdding(false);
            }}
            className="h-8 w-full rounded-md border border-primary bg-background px-2 text-sm outline-none"
          />
        </form>
      )}
      {folders.map((folder) => (
        <FolderRow key={folder.id} folder={folder} folders={folders} />
      ))}
    </section>
  );
}
