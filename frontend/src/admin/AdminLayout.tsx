import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet } from "react-router";

import { ADMIN_SECTIONS } from "@/admin/sections";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { ThemeToggle } from "@/features/theme/ThemeToggle";
import { cn } from "@/lib/utils";

export function ForbiddenPage() {
  const { t } = useTranslation();
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-3 bg-background text-foreground">
      <h1 className="text-2xl font-semibold">403</h1>
      <p className="text-muted-foreground">{t("admin.forbidden")}</p>
      <Link to="/" className="text-primary underline">
        {t("notFound.home")}
      </Link>
    </div>
  );
}

// Каркас админки (§13): часть того же SPA под /admin с отдельными правами.
export function AdminLayout() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  if (!hasPermission(me, "admin.access")) return <ForbiddenPage />;
  const sections = ADMIN_SECTIONS.filter((s) => hasPermission(me, s.permission));

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
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
      <div className="flex min-h-0 flex-1">
        <nav aria-label={t("admin.title")} className="w-56 shrink-0 border-r border-border p-2">
          {sections.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted",
                  isActive && "bg-muted font-medium",
                )
              }
            >
              <Icon className="size-4" />
              {t(label)}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
