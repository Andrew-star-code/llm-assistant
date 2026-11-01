import { Navigate } from "react-router";

import { ADMIN_SECTIONS } from "@/admin/sections";
import { hasPermission, useMe } from "@/features/auth/useMe";

/** /admin → первый доступный раздел: дашборд у админов, базы знаний у менеджера БЗ. */
export function AdminHomePage() {
  const { data: me } = useMe();
  const first = ADMIN_SECTIONS.find((s) => hasPermission(me, s.permission));
  return first ? <Navigate to={first.to} replace /> : null;
}
