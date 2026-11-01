import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router";

import { onUnauthorized } from "@/api/client";
import { NoticeDialog } from "@/features/auth/NoticeDialog";
import { ME_QUERY_KEY, useMe } from "@/features/auth/useMe";
import { ThemeServerSync } from "@/features/theme/ThemeServerSync";

/** Пускает только вошедших; иначе — на /login с возвратом обратно после входа. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { data: me, isPending, isError } = useMe();

  useEffect(
    () =>
      onUnauthorized(() => {
        queryClient.setQueryData(ME_QUERY_KEY, null);
      }),
    [queryClient],
  );

  if (isPending) {
    return (
      <div className="flex h-dvh items-center justify-center text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }
  if (isError) {
    return (
      <div className="flex h-dvh items-center justify-center text-muted-foreground">
        {t("common.apiUnavailable")}
      </div>
    );
  }
  if (!me) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return (
    <>
      <ThemeServerSync me={me} />
      {me.notice.required && <NoticeDialog text={me.notice.text} />}
      {children}
    </>
  );
}
