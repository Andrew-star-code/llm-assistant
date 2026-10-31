import { Bot, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useMatch, useNavigate } from "react-router";
import { create } from "zustand";

import { Button } from "@/components/ui/button";
import { UserMenu } from "@/features/auth/UserMenu";
import { useChat } from "@/features/chat/api";
import { ChatSidebar } from "@/features/sidebar/ChatSidebar";
import { SearchDialog } from "@/features/sidebar/SearchDialog";
import { ApiStatus } from "@/features/system/ApiStatus";
import { cn } from "@/lib/utils";

interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
}

const useSidebar = create<SidebarState>((set) => ({
  collapsed: false,
  toggle: () => {
    set((s) => ({ collapsed: !s.collapsed }));
  },
}));

/** Горячие клавиши (§7.10): Ctrl+K — поиск, Ctrl+Shift+O — новый чат. Esc — в странице чата. */
function useHotkeys(openSearch: () => void) {
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (mod && !event.shiftKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      }
      if (mod && event.shiftKey && event.code === "KeyO") {
        event.preventDefault();
        void navigate("/");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [navigate, openSearch]);
}

// Каркас §7.1: слева боковая панель (новый чат, поиск, папки, история; внизу меню пользователя),
// справа — чат: шапка с названием, лента сообщений, поле ввода.
export function AppLayout() {
  const { t } = useTranslation();
  const { collapsed, toggle } = useSidebar();
  const [searchOpen, setSearchOpen] = useState(false);
  const match = useMatch("/c/:chatId");
  const chat = useChat(match?.params.chatId);
  useHotkeys(() => {
    setSearchOpen(true);
  });
  const title = chat.data?.title ?? t("chat.newChatTitle");

  useEffect(() => {
    document.title = match ? `${title} — ${t("app.name")}` : t("app.name");
  }, [match, title, t]);

  return (
    <div className="flex h-dvh bg-background text-foreground">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-border bg-muted/40 transition-[width]",
          collapsed ? "w-14" : "w-72",
        )}
        aria-label={t("sidebar.label")}
      >
        <div className="flex items-center gap-2 p-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>
          {!collapsed && (
            <Link to="/" className="flex items-center gap-2 font-semibold">
              <Bot className="size-5 text-primary" />
              {t("app.name")}
            </Link>
          )}
        </div>
        {collapsed ? (
          <div className="flex-1" />
        ) : (
          <ChatSidebar
            onSearch={() => {
              setSearchOpen(true);
            }}
          />
        )}
        <div className="border-t border-border p-2">
          <UserMenu collapsed={collapsed} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border px-4">
          <span className="truncate font-medium" data-testid="chat-title">
            {title}
          </span>
          <ApiStatus />
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      {searchOpen && (
        <SearchDialog
          onClose={() => {
            setSearchOpen(false);
          }}
        />
      )}
    </div>
  );
}
