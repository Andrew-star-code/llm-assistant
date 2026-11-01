import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { Badge } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { Markdown } from "@/features/markdown/Markdown";
import { formatBytes, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Detail = Schemas["AdminChatDetail"];
type AdminMessage = Schemas["AdminMessage"];
type ExportFormat = Schemas["ExportIn"]["format"];

const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";

/** Активная ветка — от листа вверх по parent_id. */
function activeIds(detail: Detail): Set<string> {
  const byId = new Map(detail.messages.map((m) => [m.id, m]));
  const ids = new Set<string>();
  let current = detail.active_leaf_id ? byId.get(detail.active_leaf_id) : undefined;
  while (current) {
    ids.add(current.id);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return ids;
}

function MessageCard({
  message,
  version,
  active,
}: {
  message: AdminMessage;
  version: number;
  active: boolean;
}) {
  const { t } = useTranslation();
  const m = message;
  const meta = [
    m.model,
    m.prompt_tokens !== null || m.completion_tokens !== null
      ? t("admin.chat.tokens", {
          prompt: m.prompt_tokens ?? "—",
          completion: m.completion_tokens ?? "—",
        })
      : null,
    m.ttft_ms !== null ? t("admin.chat.ttft", { ms: m.ttft_ms }) : null,
    m.latency_ms !== null ? t("admin.chat.latency", { ms: m.latency_ms }) : null,
  ].filter(Boolean);
  return (
    <article
      id={`m-${m.id}`}
      data-testid="admin-message"
      className={cn(
        "flex scroll-mt-4 flex-col gap-2 rounded-lg border border-border p-3 target:ring-2 target:ring-primary",
        m.role === "user" ? "bg-muted/40" : "bg-background",
        !active && "opacity-80",
      )}
    >
      <header className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {t(`admin.chats.role.${m.role}`, { defaultValue: m.role })}
        </span>
        <span>{formatDateTime(m.created_at)}</span>
        {version > 1 && <Badge tone="muted">{t("admin.chat.version", { n: version })}</Badge>}
        {!active && <Badge tone="muted">{t("admin.chat.notActive")}</Badge>}
        {m.status !== "completed" && <Badge tone="warn">{m.status}</Badge>}
        {m.deleted_at && (
          <Badge tone="bad">
            {t("admin.chat.deletedMessage", { date: formatDateTime(m.deleted_at) })}
          </Badge>
        )}
        {m.feedback && (
          <Badge tone={m.feedback.rating > 0 ? "ok" : "bad"}>
            {m.feedback.rating > 0 ? t("admin.feedback.likes") : t("admin.feedback.dislikes")}
            {m.feedback.reasons.length > 0
              ? `: ${m.feedback.reasons.map((r) => t(`feedback.reasons.${r}`, { defaultValue: r })).join(", ")}`
              : ""}
          </Badge>
        )}
      </header>
      {m.feedback?.comment && (
        <p className="text-xs italic text-muted-foreground">«{m.feedback.comment}»</p>
      )}
      {m.reasoning && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            {t("admin.chat.reasoning")}
          </summary>
          <p className="whitespace-pre-wrap pt-1 text-muted-foreground">{m.reasoning}</p>
        </details>
      )}
      {m.tool_calls.length > 0 && (
        <div className="flex flex-col gap-1 text-xs" data-testid="admin-tool-calls">
          <span className="text-muted-foreground">{t("admin.chat.tools")}</span>
          {m.tool_calls.map((c, i) => (
            <details key={`${c.call_id}-${String(i)}`}>
              <summary className="cursor-pointer">
                <code>{c.tool}</code> · {c.status} ·{" "}
                {t("admin.dashboard.ms", { value: c.duration_ms })}{" "}
                {c.visibility === "hidden" && <Badge tone="warn">{t("admin.chat.hidden")}</Badge>}
              </summary>
              <pre className="mt-1 max-h-60 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap">
                {JSON.stringify(c.arguments, null, 2)}
                {c.result_preview ? `\n\n${c.result_preview}` : ""}
              </pre>
            </details>
          ))}
        </div>
      )}
      <div className="text-sm">
        <Markdown text={m.content} />
      </div>
      {m.error && (
        <p className="text-xs text-red-600">
          {t("admin.chat.error", {
            text: typeof m.error.message === "string" ? m.error.message : JSON.stringify(m.error),
          })}
        </p>
      )}
      {m.files.length > 0 && (
        <ul className="flex flex-wrap gap-2 text-xs">
          {m.files.map((f) => (
            <li key={f.id}>
              <Badge tone="muted">
                {f.filename} · {formatBytes(f.size)}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {m.sources.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            {t("admin.chat.sources")}: {m.sources.length}
          </summary>
          <ol className="flex flex-col gap-1 pt-1">
            {m.sources.map((s) => (
              <li key={s.index}>
                [{s.index}] {s.title}
                {s.page ? `, ${t("admin.chat.page", { n: s.page })}` : ""}
                {s.cited && <span className="text-emerald-600"> · {t("admin.chat.cited")}</span>}
                {s.score !== null && (
                  <span className="text-muted-foreground"> · {s.score.toFixed(3)}</span>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
      {(meta.length > 0 || m.trace) && (
        <footer className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {meta.join(" · ")}
          {m.trace && (
            <details>
              <summary className="cursor-pointer">{t("admin.chat.trace")}</summary>
              <pre className="mt-1 max-h-80 max-w-full overflow-auto rounded bg-muted p-2">
                {JSON.stringify(m.trace, null, 2)}
              </pre>
            </details>
          )}
        </footer>
      )}
    </article>
  );
}

/** Чат пользователя целиком для админа (§13.3); каждое открытие пишется в аудит. */
export function AdminChatPage() {
  const { chatId = "" } = useParams();
  const { t } = useTranslation();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState("");
  const [purging, setPurging] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("docx");

  const chat = useQuery({
    queryKey: ["admin", "chat", chatId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/chats/{chat_id}", { params: { path: { chat_id: chatId } } }),
      ),
    // Каждый запрос — запись в аудите: не перечитываем сами по себе.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const restore = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/chats/{chat_id}/restore", {
          params: { path: { chat_id: chatId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "chat", chatId] });
    },
  });
  const purge = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/chats/{chat_id}/purge", {
          params: { path: { chat_id: chatId } },
          body: { confirm },
        }),
      ),
  });
  const exporter = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/admin/exports", { body: { format, chat_id: chatId } })),
  });

  const d = chat.data;
  const active = useMemo(() => (d ? activeIds(d) : new Set<string>()), [d]);
  const versions = useMemo(() => {
    const seen = new Map<string, number>();
    const result = new Map<string, number>();
    for (const m of d?.messages ?? []) {
      const key = m.parent_id ?? "root";
      const n = (seen.get(key) ?? 0) + 1;
      seen.set(key, n);
      result.set(m.id, n);
    }
    return result;
  }, [d]);

  useEffect(() => {
    if (d && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  }, [d, location.hash]);

  if (chat.isError) {
    return (
      <p role="alert">
        {chat.error instanceof ApiError ? chat.error.message : t("common.loadError")}
      </p>
    );
  }
  if (!d) return <p className="text-muted-foreground">{t("common.loading")}</p>;

  return (
    <section className="flex max-w-4xl flex-col gap-4" data-testid="admin-chat">
      <Link to="/admin/chats" className="text-sm text-muted-foreground hover:underline">
        ← {t("admin.chat.back")}
      </Link>
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{d.title ?? t("admin.chats.untitled")}</h1>
        <p className="text-sm text-muted-foreground">
          {d.user.full_name} ({d.user.login}){d.user.department ? ` · ${d.user.department}` : ""}
          {" · "}
          {t("admin.chat.created", { date: formatDateTime(d.created_at) })}
          {d.scenario ? ` · ${t("admin.chat.scenario", { name: d.scenario.name })}` : ""}
        </p>
        <div className="flex flex-wrap gap-2">
          {d.is_test && <Badge tone="muted">{t("admin.chats.test")}</Badge>}
          {d.deleted_at && (
            <Badge tone="bad">
              {t("admin.chat.deletedAt", { date: formatDateTime(d.deleted_at) })}
              {d.deleted_by
                ? ` · ${t("admin.chat.deletedBy", { name: d.deleted_by.full_name })}`
                : ""}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t("admin.chat.audited")}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {d.deleted_at && hasPermission(me, "admin.chats.restore") && (
          <Button
            variant="outline"
            disabled={restore.isPending}
            onClick={() => {
              restore.mutate();
            }}
          >
            {t("admin.chat.restore")}
          </Button>
        )}
        {hasPermission(me, "admin.chats.export") && (
          <>
            <select
              aria-label={t("admin.chats.exportFormat")}
              className={SELECT}
              value={format}
              onChange={(e) => {
                setFormat(e.target.value as ExportFormat);
              }}
            >
              {(["docx", "pdf", "xlsx", "json"] as const).map((f) => (
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
            >
              {t("admin.chat.export")}
            </Button>
          </>
        )}
        {hasPermission(me, "admin.chats.purge") && (
          <Button
            variant="outline"
            className="text-red-600"
            onClick={() => {
              setPurging(true);
            }}
          >
            {t("admin.chat.purge")}
          </Button>
        )}
      </div>
      {restore.isSuccess && <p role="status">{t("admin.chat.restored")}</p>}
      {exporter.isSuccess && (
        <p role="status">
          <Link to="/admin/exports" className="text-primary underline">
            {t("admin.chats.exportStarted")}
          </Link>
        </p>
      )}
      {purging && (
        <div
          role="alertdialog"
          aria-labelledby="purge-title"
          className="flex flex-col gap-2 rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm"
        >
          <h2 id="purge-title" className="font-medium">
            {t("admin.chat.purgeTitle")}
          </h2>
          <p>{t("admin.chat.purgeHint", { id: d.id })}</p>
          <Input
            aria-label="id"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
            }}
          />
          {purge.isError && (
            <p role="alert" className="text-red-600">
              {purge.error instanceof ApiError ? purge.error.message : t("common.loadError")}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={confirm.trim() !== d.id || purge.isPending}
              onClick={() => {
                void purge
                  .mutateAsync()
                  .then(() => navigate("/admin/chats", { replace: true }))
                  .catch(() => undefined);
              }}
            >
              {t("admin.chat.purgeConfirm")}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setPurging(false);
              }}
            >
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {d.messages.map((m) => (
          <div key={m.id} className={cn(m.parent_id && m.role === "assistant" && "pl-4")}>
            <MessageCard message={m} version={versions.get(m.id) ?? 1} active={active.has(m.id)} />
          </div>
        ))}
      </div>
    </section>
  );
}
