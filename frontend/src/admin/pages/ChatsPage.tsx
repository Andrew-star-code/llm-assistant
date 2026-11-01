import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { LoadMore } from "@/admin/components/LoadMore";
import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

type Filter = Schemas["ChatFilter"];
type ExportFormat = Schemas["ExportIn"]["format"];

const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";
const FLAGS = ["disliked", "incident", "attachments"] as const;
const FORMATS: ExportFormat[] = ["xlsx", "json", "docx", "pdf"];

const TEXT_KEYS = ["q", "user_id", "department", "date_from", "date_to", "scenario_id", "model"];
const FLAG_KEYS = ["deleted", "disliked", "incident", "attachments"];

/** Фильтр — в адресной строке: выборкой можно поделиться и вернуться к ней из чата. */
function readFilter(params: URLSearchParams): Filter {
  const filter: Record<string, string | boolean> = {};
  for (const key of TEXT_KEYS) {
    const value = params.get(key);
    if (value) filter[key] = value;
  }
  for (const key of FLAG_KEYS) {
    const value = params.get(key);
    if (value !== null) filter[key] = value === "true";
  }
  return filter;
}

export function Fragments({ parts }: { parts: Schemas["SearchFragment"][] }) {
  return (
    <span>
      {parts.map((p, i) =>
        p.match ? (
          <mark
            key={i}
            className="rounded bg-amber-300/60 px-0.5 text-foreground dark:bg-amber-500/40"
          >
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  );
}

/** «Переписка» (§13.3): поиск по всем сообщениям, фильтры, список чатов, выгрузка выборки. */
export function ChatsPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const [params, setParams] = useSearchParams();
  const filter = readFilter(params);
  const [text, setText] = useState(filter.q ?? "");
  const [format, setFormat] = useState<ExportFormat>("xlsx");
  const searching = Boolean(filter.q);

  const options = useQuery({
    queryKey: ["admin", "chat-filters"],
    queryFn: async () => unwrap(await api.GET("/api/admin/chats/filters")),
  });
  const messages = useInfiniteQuery({
    queryKey: ["admin", "messages", filter],
    enabled: searching,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/messages", {
          params: { query: { ...filter, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const chats = useInfiniteQuery({
    queryKey: ["admin", "chats", filter],
    enabled: !searching,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/chats", { params: { query: { ...filter, cursor: pageParam } } }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const exporter = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/admin/exports", { body: { format, filter } })),
  });

  const set = (name: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined || value === "") next.delete(name);
    else next.set(name, value);
    setParams(next, { replace: true });
  };
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    set("q", text.trim());
  };
  const hits = messages.data?.pages.flatMap((p) => p.items) ?? [];
  const rows = chats.data?.pages.flatMap((p) => p.items) ?? [];
  const chatLink = (id: string, messageId?: string) =>
    `/admin/chats/${id}${messageId ? `#m-${messageId}` : ""}`;

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.chats")}</h1>
      <form onSubmit={submit} className="flex gap-2" role="search">
        <Input
          aria-label={t("admin.chats.search")}
          placeholder={t("admin.chats.search")}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          className="max-w-xl"
          data-testid="admin-chat-search"
        />
        <Button type="submit">{t("sidebar.search")}</Button>
      </form>
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="admin-chat-filters">
        <select
          aria-label={t("admin.chats.department")}
          className={SELECT}
          value={filter.department ?? ""}
          onChange={(e) => {
            set("department", e.target.value);
          }}
        >
          <option value="">
            {t("admin.chats.department")}: {t("admin.chats.any")}
          </option>
          {(options.data?.departments ?? []).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select
          aria-label={t("admin.chats.scenario")}
          className={SELECT}
          value={filter.scenario_id ?? ""}
          onChange={(e) => {
            set("scenario_id", e.target.value);
          }}
        >
          <option value="">
            {t("admin.chats.scenario")}: {t("admin.chats.any")}
          </option>
          {(options.data?.scenarios ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t("admin.chats.model")}
          className={SELECT}
          value={filter.model ?? ""}
          onChange={(e) => {
            set("model", e.target.value);
          }}
        >
          <option value="">
            {t("admin.chats.model")}: {t("admin.chats.any")}
          </option>
          {(options.data?.models ?? []).map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select
          aria-label={t("admin.chats.deleted")}
          className={SELECT}
          value={params.get("deleted") ?? ""}
          onChange={(e) => {
            set("deleted", e.target.value);
          }}
        >
          <option value="">
            {t("admin.chats.deleted")}: {t("admin.chats.any")}
          </option>
          <option value="true">{t("admin.chats.onlyDeleted")}</option>
          <option value="false">{t("admin.chats.withoutDeleted")}</option>
        </select>
        <label className="flex items-center gap-1">
          {t("admin.chats.from")}
          <Input
            type="date"
            className="h-9 w-auto"
            value={filter.date_from ?? ""}
            onChange={(e) => {
              set("date_from", e.target.value);
            }}
          />
        </label>
        <label className="flex items-center gap-1">
          {t("admin.chats.to")}
          <Input
            type="date"
            className="h-9 w-auto"
            value={filter.date_to ?? ""}
            onChange={(e) => {
              set("date_to", e.target.value);
            }}
          />
        </label>
        {FLAGS.map((flag) => (
          <label key={flag} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={params.get(flag) === "true"}
              onChange={(e) => {
                set(flag, e.target.checked ? "true" : undefined);
              }}
            />
            {t(`admin.chats.${flag}`)}
          </label>
        ))}
        {params.size > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setText("");
              setParams(new URLSearchParams(), { replace: true });
            }}
          >
            {t("admin.chats.reset")}
          </Button>
        )}
      </div>

      {searching ? (
        <>
          <h2 className="text-sm font-medium text-muted-foreground">{t("admin.chats.found")}</h2>
          <Table
            head={[
              t("admin.chats.activity"),
              t("admin.chats.owner"),
              t("admin.chats.chat"),
              t("admin.chats.found"),
            ]}
          >
            {hits.map((h) => (
              <tr key={h.message_id} data-testid="admin-message-hit">
                <Td className="whitespace-nowrap">{formatDateTime(h.created_at)}</Td>
                <Td>
                  <div>{h.user.full_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {h.user.login}
                    {h.user.department ? ` · ${h.user.department}` : ""}
                  </div>
                </Td>
                <Td>
                  <Link
                    to={chatLink(h.chat_id, h.message_id)}
                    className="font-medium hover:underline"
                  >
                    {h.chat_title ?? t("admin.chats.untitled")}
                  </Link>
                  <div className="flex flex-wrap gap-1 pt-1">
                    {h.deleted && <Badge tone="bad">{t("admin.chats.deletedBadge")}</Badge>}
                    {h.is_test && <Badge tone="muted">{t("admin.chats.test")}</Badge>}
                    {h.disliked && <Badge tone="warn">{t("admin.chats.disliked")}</Badge>}
                    {h.has_incident && <Badge tone="bad">{t("admin.chats.incident")}</Badge>}
                  </div>
                </Td>
                <Td>
                  <div className="text-xs text-muted-foreground">
                    {t(`admin.chats.role.${h.role}`, { defaultValue: h.role })}
                  </div>
                  <Fragments parts={h.fragments} />
                </Td>
              </tr>
            ))}
          </Table>
          {messages.isSuccess && hits.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("common.nothingFound")}</p>
          )}
          <LoadMore
            hasMore={messages.hasNextPage}
            loading={messages.isFetchingNextPage}
            onClick={() => {
              void messages.fetchNextPage();
            }}
          />
        </>
      ) : (
        <>
          <Table
            head={[
              t("admin.chats.activity"),
              t("admin.chats.owner"),
              t("admin.chats.chat"),
              t("admin.chats.messages"),
            ]}
          >
            {rows.map((c) => (
              <tr key={c.id} data-testid="admin-chat-row">
                <Td className="whitespace-nowrap">
                  {formatDateTime(c.last_message_at ?? c.created_at)}
                </Td>
                <Td>
                  <div>{c.user.full_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {c.user.login}
                    {c.user.department ? ` · ${c.user.department}` : ""}
                  </div>
                </Td>
                <Td>
                  <Link to={chatLink(c.id)} className="font-medium hover:underline">
                    {c.title ?? t("admin.chats.untitled")}
                  </Link>
                  <div className="flex flex-wrap gap-1 pt-1">
                    {c.scenario && <Badge tone="muted">{c.scenario}</Badge>}
                    {c.deleted_at && <Badge tone="bad">{t("admin.chats.deletedBadge")}</Badge>}
                    {c.is_test && <Badge tone="muted">{t("admin.chats.test")}</Badge>}
                    {c.disliked > 0 && (
                      <Badge tone="warn">
                        {t("admin.chats.disliked")}: {c.disliked}
                      </Badge>
                    )}
                    {c.incidents > 0 && (
                      <Badge tone="bad">
                        {t("admin.chats.incident")}: {c.incidents}
                      </Badge>
                    )}
                  </div>
                </Td>
                <Td className="tabular-nums">{c.messages}</Td>
              </tr>
            ))}
          </Table>
          {chats.isSuccess && rows.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("common.nothingFound")}</p>
          )}
          <LoadMore
            hasMore={chats.hasNextPage}
            loading={chats.isFetchingNextPage}
            onClick={() => {
              void chats.fetchNextPage();
            }}
          />
        </>
      )}

      {hasPermission(me, "admin.chats.export") && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4 text-sm">
          <select
            aria-label={t("admin.chats.exportFormat")}
            className={SELECT}
            value={format}
            onChange={(e) => {
              setFormat(e.target.value as ExportFormat);
            }}
          >
            {FORMATS.map((f) => (
              <option key={f} value={f}>
                {t(`admin.exports.formats.${f}`)}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            disabled={exporter.isPending}
            onClick={() => {
              exporter.mutate();
            }}
            data-testid="admin-export-selection"
          >
            {t("admin.chats.export")}
          </Button>
          {exporter.isSuccess && (
            <p role="status">
              <Link to="/admin/exports" className="text-primary underline">
                {t("admin.chats.exportStarted")}
              </Link>
            </p>
          )}
          {exporter.isError && (
            <p role="alert" className="text-red-600">
              {exporter.error instanceof ApiError ? exporter.error.message : t("common.loadError")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
