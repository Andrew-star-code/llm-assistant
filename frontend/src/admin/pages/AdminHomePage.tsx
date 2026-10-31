import { useTranslation } from "react-i18next";

export function AdminHomePage() {
  const { t } = useTranslation();
  return <p className="text-muted-foreground">{t("admin.stagePlaceholder")}</p>;
}
