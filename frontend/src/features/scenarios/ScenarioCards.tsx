import { useTranslation } from "react-i18next";

import type { ScenarioCard } from "@/features/scenarios/api";
import { ScenarioIcon } from "@/features/scenarios/icons";
import { cn } from "@/lib/utils";

/** Карточки сценариев на стартовом экране (§7.9): иконка, название, строка описания. */
export function ScenarioCards({
  scenarios,
  selectedId,
  onSelect,
}: {
  scenarios: ScenarioCard[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const { t } = useTranslation();
  if (!scenarios.length) return null;
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-sm font-medium text-muted-foreground">{t("scenarios.title")}</h2>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="scenario-cards">
        {scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-pressed={selectedId === s.id}
            data-testid="scenario-card"
            onClick={() => {
              onSelect(selectedId === s.id ? null : s.id);
            }}
            className={cn(
              "flex gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:bg-muted",
              selectedId === s.id && "border-primary bg-primary/5",
            )}
          >
            <ScenarioIcon name={s.icon} className="mt-0.5 size-5 shrink-0 text-primary" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{s.name}</span>
              {s.description && (
                <span className="line-clamp-2 text-xs text-muted-foreground">{s.description}</span>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
