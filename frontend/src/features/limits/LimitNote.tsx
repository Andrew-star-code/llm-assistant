import { useTranslation } from "react-i18next";

import {
  amount,
  blockingItem,
  exhaustedText,
  resetWhen,
  type MyLimits,
} from "@/features/limits/api";
import { cn } from "@/lib/utils";

/** Строка под полем ввода: остаток по метрике, ближайшей к исчерпанию, или почему поле закрыто. */
export function LimitNote({ limits }: { limits: MyLimits | undefined }) {
  const { t } = useTranslation();
  const blocking = blockingItem(limits);
  if (blocking) {
    return (
      <p role="alert" className="px-2 pt-1 text-xs text-red-600" data-testid="limit-blocked">
        {exhaustedText(t, blocking, limits?.timezone)}
      </p>
    );
  }
  const near = limits?.nearest;
  if (!near) return null;
  const what = t(`limits.genitive.${near.metric}`);
  const text =
    t("limits.remaining", {
      remaining: amount(near.metric, near.remaining),
      limit: amount(near.metric, near.limit),
      what,
    }) +
    (near.reset_at
      ? t("limits.resetsShort", { when: resetWhen(t, near.reset_at, limits.timezone) })
      : "");
  const low = near.limit > 0 && near.remaining / near.limit <= 0.1;
  return (
    <p
      className={cn("px-2 pt-1 text-xs", low ? "text-amber-600" : "text-muted-foreground")}
      data-testid="limit-note"
    >
      {text}
    </p>
  );
}
