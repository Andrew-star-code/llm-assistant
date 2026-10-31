import { Check, Loader2, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ToolStepView } from "@/features/chat/live";

/**
 * Строки статуса инструментов (§7.4): «Читаю Отчёт.docx…», «Создаю таблицу…». Текст — по i18n-ключу
 * из события, неизвестный инструмент показывается нейтральной строкой.
 */
export function ToolSteps({ steps }: { steps: ToolStepView[] }) {
  const { t } = useTranslation();
  if (!steps.length) return null;
  return (
    <ul className="mb-2 space-y-1 text-sm text-muted-foreground" data-testid="tool-steps">
      {steps.map((step) => {
        const text = t(step.label, {
          ...step.params,
          defaultValue: t("tools.unknown", { tool: step.tool }),
        });
        return (
          <li
            key={step.callId}
            className="flex items-center gap-2"
            data-testid="tool-step"
            data-status={step.status}
          >
            {step.status === "running" ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : step.status === "ok" ? (
              <Check className="size-3.5 text-green-600" aria-hidden />
            ) : (
              <TriangleAlert className="size-3.5 text-amber-600" aria-hidden />
            )}
            <span className={step.status === "running" ? "animate-pulse" : undefined}>
              {text}
              {step.status === "running" ? "…" : ""}
              {step.status === "error" || step.status === "timeout"
                ? ` — ${t(`tools.status.${step.status}`)}`
                : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
