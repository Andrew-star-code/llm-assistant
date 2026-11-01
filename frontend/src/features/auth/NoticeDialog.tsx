import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ME_QUERY_KEY } from "@/features/auth/useMe";

/** Уведомление при первом входе: переписка сохраняется и может проверяться (§7.10, §15). */
export function NoticeDialog({ text }: { text: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const accept = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/auth/notice/accept"));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="notice-title"
        className="w-full max-w-lg rounded-lg border border-border bg-background p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center gap-3">
          <ShieldCheck className="size-6 text-primary" />
          <h2 id="notice-title" className="text-lg font-semibold">
            {t("notice.title")}
          </h2>
        </div>
        <p className="whitespace-pre-line text-sm leading-relaxed">{text}</p>
        <div className="mt-6 flex justify-end">
          <Button
            onClick={() => {
              accept.mutate();
            }}
            disabled={accept.isPending}
          >
            {t("notice.accept")}
          </Button>
        </div>
      </div>
    </div>
  );
}
