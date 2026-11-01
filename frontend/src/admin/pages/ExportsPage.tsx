import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { formatBytes, formatDateTime } from "@/lib/format";

const TONE = {
  queued: "muted",
  running: "warn",
  ready: "ok",
  error: "bad",
  expired: "muted",
} as const;

/** Свои выгрузки переписки (§13.3): статус, срок хранения, скачивание. */
export function ExportsPage() {
  const { t } = useTranslation();
  const exports = useQuery({
    queryKey: ["admin", "exports"],
    queryFn: async () => unwrap(await api.GET("/api/admin/exports")),
    // Пока выгрузка собирается — опрашиваем.
    refetchInterval: (query) =>
      query.state.data?.some((e) => e.status === "queued" || e.status === "running") ? 2000 : false,
  });
  const items = exports.data ?? [];
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.exports")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.exports.hint")}</p>
      <Table
        head={[
          t("admin.exports.created"),
          t("admin.exports.format"),
          t("admin.exports.source"),
          t("admin.exports.status"),
          t("admin.exports.volume"),
          t("admin.exports.expires"),
          "",
        ]}
      >
        {items.map((e) => (
          <tr key={e.id} data-testid="export-row">
            <Td className="whitespace-nowrap">{formatDateTime(e.created_at)}</Td>
            <Td>{t(`admin.exports.formats.${e.format}`)}</Td>
            <Td className="max-w-xs text-xs">
              {"chat_id" in e.filter ? t("admin.exports.oneChat") : t("admin.exports.selection")}
              <code className="block break-all text-muted-foreground">
                {JSON.stringify(e.filter)}
              </code>
            </Td>
            <Td>
              <Badge tone={TONE[e.status]}>{t(`admin.exports.statuses.${e.status}`)}</Badge>
              {e.error && <div className="pt-1 text-xs text-red-600">{e.error}</div>}
            </Td>
            <Td className="text-xs">
              {e.chats !== null && e.messages !== null
                ? t("admin.exports.volumeText", { chats: e.chats, messages: e.messages })
                : "—"}
              {e.size !== null && (
                <div className="text-muted-foreground">{formatBytes(e.size)}</div>
              )}
            </Td>
            <Td className="whitespace-nowrap">{formatDateTime(e.expires_at)}</Td>
            <Td>
              {e.status === "ready" && (
                <a
                  href={`/api/admin/exports/${e.id}/download`}
                  className="text-primary underline"
                  download
                >
                  {t("admin.exports.download")}
                </a>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      {exports.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.exports.empty")}</p>
      )}
    </section>
  );
}
