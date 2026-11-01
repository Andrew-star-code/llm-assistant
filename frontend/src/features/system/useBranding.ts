import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api, unwrap } from "@/api/client";

/** Название и логотип из админки «Настройки» (§13.2); до ответа — название из i18n. */
export function useBranding(): { name: string; logoUrl: string | null } {
  const { t } = useTranslation();
  const branding = useQuery({
    queryKey: ["branding"],
    queryFn: async () => unwrap(await api.GET("/api/branding")),
    staleTime: 5 * 60_000,
  });
  return {
    name: branding.data?.app_name ?? t("app.name"),
    logoUrl: branding.data?.logo_url ?? null,
  };
}
