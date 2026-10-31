import { Bot, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router";
import { create } from "zustand";

import { Button } from "@/components/ui/button";
import { UserMenu } from "@/features/auth/UserMenu";
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

// Каркас §7.1: слева боковая панель (новый чат, поиск, папки, чаты; внизу меню пользователя),
// справа — чат. На этапе 0 — только структура; содержимое появится на этапах 1–2.
export function AppLayout() {
  const { t } = useTranslation();
  const { collapsed, toggle } = useSidebar();

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
        <div className="p-2">
          <Button className="w-full justify-start" disabled title={t("common.comingSoon")}>
            <Plus />
            {!collapsed && t("sidebar.newChat")}
          </Button>
        </div>
        {!collapsed && (
          <p className="px-4 py-2 text-sm text-muted-foreground">{t("sidebar.emptyHistory")}</p>
        )}
        <div className="mt-auto border-t border-border p-2">
          <UserMenu collapsed={collapsed} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-4 border-b border-border px-4">
          <span className="truncate font-medium">{t("chat.newChatTitle")}</span>
          <ApiStatus />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
