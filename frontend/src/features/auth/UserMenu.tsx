import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge, LogOut, Shield, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { api, unwrap } from "@/api/client";
import { Avatar } from "@/components/ui/avatar";
import { hasPermission, useMe, useSetMe } from "@/features/auth/useMe";
import { ThemeToggle } from "@/features/theme/ThemeToggle";

const ITEM = "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-muted";

/** Меню внизу боковой панели (§7.1): профиль, админка (по праву), тема, выход. */
export function UserMenu({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const setMe = useSetMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const logout = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/auth/logout"));
    },
    onSettled: () => {
      queryClient.clear();
      setMe(null);
      void navigate("/login", { replace: true });
    },
  });

  if (!me) return null;
  const photo = me.has_photo ? "/api/profile/photo" : null;

  return (
    <div ref={ref} className="relative">
      {open && (
        <div
          role="menu"
          aria-label={t("userMenu.label")}
          className="absolute bottom-full left-0 z-20 mb-2 w-64 rounded-lg border border-border bg-background p-1 shadow-lg"
        >
          <div className="px-2 py-2">
            <div className="truncate text-sm font-medium">{me.full_name}</div>
            <div className="truncate text-xs text-muted-foreground">{me.title}</div>
          </div>
          <Link
            role="menuitem"
            to="/profile"
            className={ITEM}
            onClick={() => {
              setOpen(false);
            }}
          >
            <UserRound className="size-4" />
            {t("userMenu.profile")}
          </Link>
          <Link
            role="menuitem"
            to="/profile#limits"
            className={ITEM}
            onClick={() => {
              setOpen(false);
            }}
          >
            <Gauge className="size-4" />
            {t("userMenu.limits")}
          </Link>
          {hasPermission(me, "admin.access") && (
            <Link
              role="menuitem"
              to="/admin"
              className={ITEM}
              onClick={() => {
                setOpen(false);
              }}
            >
              <Shield className="size-4" />
              {t("userMenu.admin")}
            </Link>
          )}
          <div className="flex items-center justify-between px-2 py-2 text-sm">
            {t("theme.label")}
            <ThemeToggle />
          </div>
          <button
            role="menuitem"
            type="button"
            className={ITEM}
            onClick={() => {
              logout.mutate();
            }}
          >
            <LogOut className="size-4" />
            {t("userMenu.logout")}
          </button>
        </div>
      )}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="user-menu"
        onClick={() => {
          setOpen(!open);
        }}
        className="flex w-full items-center gap-2 rounded-md p-2 text-left hover:bg-muted"
      >
        <Avatar name={me.full_name} src={photo} />
        {!collapsed && <span className="truncate text-sm">{me.full_name}</span>}
      </button>
    </div>
  );
}
