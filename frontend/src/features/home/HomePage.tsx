import { useTranslation } from "react-i18next";

import { greetingKey } from "@/features/home/greeting";

// Стартовый экран §7.1: приветствие по имени и отчеству с учётом времени суток,
// карточки сценариев и примеры запросов. Имя появится после входа (этап 1), сценарии — этап 5.
export function HomePage() {
  const { t } = useTranslation();
  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t(greetingKey(new Date()))}</h1>
      <p className="text-muted-foreground">{t("home.subtitle")}</p>
      <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        {t("home.stagePlaceholder")}
      </div>
    </section>
  );
}
