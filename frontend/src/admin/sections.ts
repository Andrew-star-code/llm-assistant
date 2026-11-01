import {
  Cpu,
  Download,
  LayoutDashboard,
  Library,
  MessagesSquare,
  Settings,
  ThumbsUp,
  Wrench,
  Network,
  ScrollText,
  ShieldAlert,
  Siren,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

interface Section {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Нужно любое из прав. */
  permission: string | string[];
}

// Разделы админки (§13.2). Видны только при наличии права; сервер проверяет права сам.
export const ADMIN_SECTIONS: Section[] = [
  {
    to: "/admin/dashboard",
    label: "admin.nav.dashboard",
    icon: LayoutDashboard,
    permission: "admin.dashboard.view",
  },
  {
    to: "/admin/chats",
    label: "admin.nav.chats",
    icon: MessagesSquare,
    permission: "admin.chats.view",
  },
  {
    to: "/admin/exports",
    label: "admin.nav.exports",
    icon: Download,
    permission: "admin.chats.export",
  },
  {
    to: "/admin/feedback",
    label: "admin.nav.feedback",
    icon: ThumbsUp,
    permission: "admin.feedback.view",
  },
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
  {
    to: "/admin/kb",
    label: "admin.nav.kb",
    icon: Library,
    permission: ["admin.kb.manage", "admin.kb.manage_roles"],
  },
  {
    to: "/admin/scenarios",
    label: "admin.nav.scenarios",
    icon: Sparkles,
    permission: "admin.scenarios.manage",
  },
  {
    to: "/admin/incidents",
    label: "admin.nav.incidents",
    icon: Siren,
    permission: "admin.incidents.view",
  },
  { to: "/admin/models", label: "admin.nav.models", icon: Cpu, permission: "admin.models.manage" },
  { to: "/admin/tools", label: "admin.nav.tools", icon: Wrench, permission: "admin.tools.manage" },
  {
    to: "/admin/settings",
    label: "admin.nav.settings",
    icon: Settings,
    permission: "admin.settings.manage",
  },
];
