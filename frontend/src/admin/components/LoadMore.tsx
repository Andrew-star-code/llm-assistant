import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

export function LoadMore({
  hasMore,
  loading,
  onClick,
}: {
  hasMore: boolean;
  loading: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  if (!hasMore) return null;
  return (
    <div className="flex justify-center py-4">
      <Button variant="outline" size="sm" disabled={loading} onClick={onClick}>
        {t("common.loadMore")}
      </Button>
    </div>
  );
}
