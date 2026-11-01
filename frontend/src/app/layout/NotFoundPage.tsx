import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-background text-foreground">
      <h1 className="text-2xl font-semibold">{t("notFound.title")}</h1>
      <Link to="/" className="text-primary underline">
        {t("notFound.home")}
      </Link>
    </div>
  );
}
