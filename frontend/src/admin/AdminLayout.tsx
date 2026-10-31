import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router";

import { ThemeToggle } from "@/features/theme/ThemeToggle";

// Каркас админки (§13). Разделы и проверка прав — этапы 1 и 6.
export function AdminLayout() {
  const { t } = useTranslation();
  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="text-muted-foreground hover:text-foreground"
            aria-label={t("admin.back")}
          >
            <ArrowLeft className="size-5" />
          </Link>
          <span className="font-semibold">{t("admin.title")}</span>
        </div>
        <ThemeToggle />
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
