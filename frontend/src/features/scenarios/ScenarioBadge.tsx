import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ScenarioIcon } from "@/features/scenarios/icons";

/** Индикатор активного сценария с кнопкой сброса (§7.3). */
export function ScenarioBadge({
  name,
  icon,
  onReset,
}: {
  name: string;
  icon: string | null;
  onReset?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 py-0.5 pl-2 pr-1 text-xs text-primary"
      data-testid="scenario-badge"
    >
      <ScenarioIcon name={icon} className="size-3.5" />
      <span>{name}</span>
      {onReset && (
        <button
          type="button"
          className="rounded-full p-0.5 hover:bg-primary/20"
          aria-label={t("scenarios.reset")}
          title={t("scenarios.reset")}
          onClick={onReset}
        >
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}
