import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet } from "react-router";

import { ADMIN_SECTIONS } from "@/admin/sections";
import { api, unwrap } from "@/api/client";
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
/** Счётчик новых инцидентов в меню (§13.5): high и critical подсвечены. */
function IncidentsBadge() {
  const { t } = useTranslation();
  const summary = useQuery({
    queryKey: ["admin", "incidents-summary"],
    queryFn: async () => unwrap(await api.GET("/api/admin/incidents/summary")),
    refetchInterval: 60_000,
  });
  const s = summary.data;
  if (!s || s.new === 0) return null;
  return (
    <span
      data-testid="incidents-badge"
      aria-label={t("admin.incidents.badge", { count: s.new })}
      className={cn(
        "ml-auto rounded-full px-1.5 text-xs tabular-nums",
        s.new_high > 0 ? "bg-red-600 text-white" : "bg-muted-foreground/20",
      )}
    >
      {s.new}
    </span>
  );
}

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
              {to === "/admin/incidents" && <IncidentsBadge />}
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
