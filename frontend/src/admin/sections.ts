import { Network, ScrollText, ShieldAlert, Users, type LucideIcon } from "lucide-react";

interface Section {
  to: string;
  label: string;
  icon: LucideIcon;
  permission: string;
}

// Разделы админки этапа 1 (§13.2). Видны только при наличии права; сервер проверяет права сам.
export const ADMIN_SECTIONS: Section[] = [
  { to: "/admin/users", label: "admin.nav.users", icon: Users, permission: "admin.users.view" },
  {
    to: "/admin/logins",
    label: "admin.nav.logins",
    icon: ShieldAlert,
    permission: "admin.logins.view",
  },
  {
    to: "/admin/audit",
    label: "admin.nav.audit",
    icon: ScrollText,
    permission: "admin.audit.view",
  },
  { to: "/admin/ad", label: "admin.nav.ad", icon: Network, permission: "admin.ad.diagnostics" },
];
