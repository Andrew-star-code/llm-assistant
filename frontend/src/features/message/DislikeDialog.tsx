import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";

type Reason = Schemas["FeedbackIn"]["reasons"] extends (infer R)[] | undefined ? R : never;
const REASONS: Reason[] = ["inaccurate", "off_topic", "code_error", "incomplete", "other"];

/** Дизлайк: причина и комментарий (§7.4). */
export function DislikeDialog({
  onSubmit,
  onClose,
}: {
  onSubmit: (reasons: Reason[], comment: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [comment, setComment] = useState("");
  const toggle = (reason: Reason) => {
    setReasons((prev) =>
      prev.includes(reason) ? prev.filter((r) => r !== reason) : [...prev, reason],
    );
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dislike-title"
        className="w-full max-w-md rounded-lg border border-border bg-background p-5 shadow-xl"
        onMouseDown={(e) => {
          e.stopPropagation();
        }}
      >
        <h2 id="dislike-title" className="mb-3 font-semibold">
          {t("feedback.title")}
        </h2>
        <div className="flex flex-wrap gap-2">
          {REASONS.map((reason) => (
            <button
              key={reason}
              type="button"
              aria-pressed={reasons.includes(reason)}
              onClick={() => {
                toggle(reason);
              }}
              className="rounded-full border border-border px-3 py-1 text-xs aria-pressed:border-primary aria-pressed:bg-primary/10 aria-pressed:text-primary"
            >
              {t(`feedback.reasons.${reason}`)}
            </button>
          ))}
        </div>
        <textarea
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
          }}
          rows={3}
          maxLength={2000}
          aria-label={t("feedback.comment")}
          placeholder={t("feedback.comment")}
          className="mt-3 w-full rounded-md border border-border bg-background p-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => {
              onSubmit(reasons, comment);
            }}
          >
            {t("feedback.send")}
          </Button>
        </div>
      </div>
    </div>
  );
}
