import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";
import { formatDateTime } from "@/lib/format";

const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";
const REASONS = ["inaccurate", "off_topic", "code_error", "incomplete", "other"];

/** «Обратная связь» (§13.2): оценки с причинами, переход в чат, выгрузка XLSX. */
export function FeedbackPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const rating = params.get("rating") ?? "";
  const reason = params.get("reason") ?? "";
  const query = {
    rating: rating ? Number(rating) : undefined,
    reason: reason || undefined,
  };
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  const stats = useQuery({
    queryKey: ["admin", "feedback-stats", query],
    queryFn: async () => unwrap(await api.GET("/api/admin/feedback/stats", { params: { query } })),
  });
  const list = useInfiniteQuery({
    queryKey: ["admin", "feedback", query],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/feedback", {
          params: { query: { ...query, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const exportUrl = `/api/admin/feedback/export?${new URLSearchParams(
    Object.entries(query).flatMap(([k, v]) => (v === undefined ? [] : [[k, String(v)]])),
  ).toString()}`;

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.feedback")}</h1>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select
          aria-label={t("admin.feedback.rating")}
          className={SELECT}
          value={rating}
          onChange={(e) => {
            set("rating", e.target.value);
          }}
        >
          <option value="">
            {t("admin.feedback.rating")}: {t("admin.feedback.any")}
          </option>
          <option value="1">{t("admin.feedback.likes")}</option>
          <option value="-1">{t("admin.feedback.dislikes")}</option>
        </select>
        <select
          aria-label={t("admin.feedback.reason")}
          className={SELECT}
          value={reason}
          onChange={(e) => {
            set("reason", e.target.value);
          }}
        >
          <option value="">
            {t("admin.feedback.reason")}: {t("admin.feedback.any")}
          </option>
          {REASONS.map((r) => (
            <option key={r} value={r}>
              {t(`feedback.reasons.${r}`)}
            </option>
          ))}
        </select>
        {stats.data && (
          <span className="text-muted-foreground" data-testid="feedback-summary">
            {t("admin.feedback.summary", {
              likes: stats.data.likes,
              dislikes: stats.data.dislikes,
            })}
          </span>
        )}
        <a href={exportUrl} className="ml-auto text-primary underline" download>
          {t("admin.feedback.export")}
        </a>
      </div>
      <Table
        head={[
          t("admin.feedback.when"),
          t("admin.feedback.who"),
          t("admin.feedback.rating"),
          t("admin.feedback.question"),
          t("admin.feedback.answer"),
        ]}
      >
        {items.map((f) => (
          <tr key={f.id} data-testid="feedback-row">
            <Td className="whitespace-nowrap">{formatDateTime(f.created_at)}</Td>
            <Td>
              <div>{f.user.full_name}</div>
              <div className="text-xs text-muted-foreground">
                {f.user.department ?? f.user.login}
              </div>
            </Td>
            <Td>
              <Badge tone={f.rating > 0 ? "ok" : "bad"}>
                {f.rating > 0 ? t("admin.feedback.likes") : t("admin.feedback.dislikes")}
              </Badge>
              <div className="pt-1 text-xs">
                {f.reasons.map((r) => t(`feedback.reasons.${r}`, { defaultValue: r })).join(", ")}
              </div>
              {f.comment && <div className="pt-1 text-xs italic">«{f.comment}»</div>}
            </Td>
            <Td className="max-w-xs text-xs">{f.question}</Td>
            <Td className="max-w-sm text-xs">
              <div className="line-clamp-4">{f.answer}</div>
              <Link
                to={`/admin/chats/${f.chat_id}#m-${f.message_id}`}
                className="text-primary underline"
              >
                {t("admin.feedback.openChat")}
              </Link>
            </Td>
          </tr>
        ))}
      </Table>
      {list.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("common.nothingFound")}</p>
      )}
      <LoadMore
        hasMore={list.hasNextPage}
        loading={list.isFetchingNextPage}
        onClick={() => {
          void list.fetchNextPage();
        }}
      />
    </section>
  );
}
