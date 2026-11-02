import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { Badge } from "@/admin/components/Table";
import { SEVERITY_TONE, STATUS_TONE, tone } from "@/admin/incidents";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

type Detail = Schemas["IncidentDetail"];
type Status = NonNullable<Schemas["IncidentUpdate"]["status"]>;
type Payload = Record<string, unknown>;

const STATUSES: Status[] = ["new", "in_progress", "resolved", "false_positive"];
const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";
const PRE = "max-h-96 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap";

/** Лог открывается на последних строках: самое важное (сбой, остановка) — в конце. */
function LogPre({ value }: { value: unknown }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [value]);
  return (
    <pre ref={ref} className={PRE} data-testid="incident-log">
      {lines(value)}
    </pre>
  );
}

function text(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function lines(value: unknown): string {
  return Array.isArray(value) ? value.map(text).join("\n") : text(value);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

/** Полезная нагрузка по типу инцидента (§13.5): стек и логи, репорт, вердикт, правило, логи модели. */
function PayloadView({ incident }: { incident: Detail }) {
  const { t } = useTranslation();
  const p: Payload = incident.payload ?? {};
  const k = (key: string) => t(`admin.incidents.${key}`);
  switch (incident.type) {
    case "system_error":
      return (
        <div className="flex flex-col gap-3" data-testid="incident-payload">
          <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm">
            <Row label={k("endpoint")}>
              {text(p.method)} {text(p.path)}
            </Row>
            <Row label={k("requestId")}>
              <code>{text(p.request_id)}</code>
            </Row>
            <Row label={k("environment")}>{text(p.environment)}</Row>
          </dl>
          <h3 className="text-sm font-medium">{k("stack")}</h3>
          <pre className={PRE}>{text(p.stack)}</pre>
          <h3 className="text-sm font-medium">{k("logs")}</h3>
          <LogPre value={p.logs} />
          <details>
            <summary className="cursor-pointer text-sm">{k("recentLogs")}</summary>
            <LogPre value={p.recent_logs} />
          </details>
        </div>
      );
    case "model_report":
      return (
        <dl
          className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm"
          data-testid="incident-payload"
        >
          <Row label={k("category")}>{text(p.category_name)}</Row>
          <Row label={k("severity")}>{text(p.severity)}</Row>
          <Row label={k("summary")}>{text(p.summary)}</Row>
          {p.first_evidence !== undefined && p.first_evidence !== p.evidence && (
            <Row label={k("firstEvidence")}>
              <blockquote className="border-l-2 border-border pl-2 italic">
                {text(p.first_evidence)}
              </blockquote>
            </Row>
          )}
          <Row
            label={k(
              p.first_evidence !== undefined && p.first_evidence !== p.evidence
                ? "lastEvidence"
                : "evidence",
            )}
          >
            <blockquote className="border-l-2 border-border pl-2 italic">
              {text(p.evidence)}
            </blockquote>
          </Row>
        </dl>
      );
    case "guard":
      return (
        <dl
          className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm"
          data-testid="incident-payload"
        >
          <Row label={k("verdict")}>{text(p.verdict)}</Row>
          <Row label={k("categories")}>{lines(p.categories)}</Row>
          <Row label={k("excerpt")}>
            <blockquote className="border-l-2 border-border pl-2 italic">
              {text(p.message_excerpt)}
            </blockquote>
          </Row>
          <Row label={k("blocked")}>{p.blocked ? t("common.yes") : t("common.no")}</Row>
        </dl>
      );
    case "security":
      return (
        <dl
          className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm"
          data-testid="incident-payload"
        >
          <Row label={k("rule")}>{text(p.rule)}</Row>
          {p.ip !== undefined && <Row label={k("ip")}>{text(p.ip)}</Row>}
          {p.blocked_until !== undefined && (
            <Row label={k("blockedUntil")}>
              {typeof p.blocked_until === "string" ? formatDateTime(p.blocked_until) : "—"}
            </Row>
          )}
          {Array.isArray(p.logins) && (
            <Row label={k("logins")}>{p.logins.map(text).join(", ")}</Row>
          )}
          {p.login !== undefined && <Row label={k("user")}>{text(p.login)}</Row>}
        </dl>
      );
    case "model_health":
      return (
        <div className="flex flex-col gap-3" data-testid="incident-payload">
          <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm">
            <Row label={k("model")}>
              {text(p.role)} · {text(p.model)} · {text(p.base_url)}
            </Row>
            <Row label={k("detail")}>{text(p.detail)}</Row>
          </dl>
          <h3 className="text-sm font-medium">{k("containerLogs")}</h3>
          {Array.isArray(p.container_logs) ? (
            <LogPre value={p.container_logs} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("admin.incidents.noLogs", { note: text(p.logs_note) })}
            </p>
          )}
        </div>
      );
    default:
      return <pre className={PRE}>{JSON.stringify(p, null, 2)}</pre>;
  }
}

function Workflow({ incident }: { incident: Detail }) {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>(incident.status as Status);
  const [assignee, setAssignee] = useState(incident.assignee?.id ?? "");
  const [resolution, setResolution] = useState(incident.resolution ?? "");
  const [comment, setComment] = useState("");
  const people = useQuery({
    queryKey: ["admin", "incident-assignees"],
    queryFn: async () => unwrap(await api.GET("/api/admin/incidents/assignees")),
  });
  const done = (data: Detail) => {
    queryClient.setQueryData(["admin", "incident", incident.id], data);
    void queryClient.invalidateQueries({ queryKey: ["admin", "incidents"] });
    void queryClient.invalidateQueries({ queryKey: ["admin", "incidents-summary"] });
  };
  const path = { params: { path: { incident_id: incident.id } } };
  const save = useMutation({
    mutationFn: async (body: Schemas["IncidentUpdate"]) =>
      unwrap(await api.PATCH("/api/admin/incidents/{incident_id}", { ...path, body })),
    onSuccess: (data) => {
      setStatus(data.status as Status);
      setAssignee(data.assignee?.id ?? "");
      setResolution(data.resolution ?? "");
      done(data);
    },
  });
  // Правка после сохранения снова делает форму «несохранённой».
  const edit =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      save.reset();
      set(value);
    };
  const addComment = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/incidents/{incident_id}/comments", {
          ...path,
          body: { text: comment },
        }),
      ),
    onSuccess: (data) => {
      setComment("");
      done(data);
    },
  });
  const error = save.error ?? addComment.error;
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
      data-testid="incident-workflow"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select
          aria-label={t("admin.incidents.status")}
          className={SELECT}
          value={status}
          onChange={(e) => {
            edit(setStatus)(e.target.value as Status);
          }}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`admin.incidents.statuses.${s}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("admin.incidents.assignee")}
          className={SELECT}
          value={assignee}
          onChange={(e) => {
            edit(setAssignee)(e.target.value);
          }}
        >
          <option value="">{t("admin.incidents.nobody")}</option>
          {(people.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.full_name}
            </option>
          ))}
        </select>
        {me && assignee !== me.id && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              edit(setAssignee)(me.id);
            }}
          >
            {t("admin.incidents.takeMe")}
          </Button>
        )}
      </div>
      <textarea
        aria-label={t("admin.incidents.resolution")}
        placeholder={t("admin.incidents.resolution")}
        className="min-h-16 rounded-md border border-border bg-background p-2 text-sm"
        value={resolution}
        onChange={(e) => {
          edit(setResolution)(e.target.value);
        }}
      />
      <Button
        className="w-fit"
        disabled={save.isPending || !hasPermission(me, "admin.incidents.manage")}
        onClick={() => {
          save.mutate({ status, assigned_to: assignee || null, resolution: resolution || null });
        }}
      >
        {t("admin.incidents.save")}
      </Button>
      {save.isSuccess && (
        <p role="status" className="text-sm">
          {t("admin.incidents.saved")}
        </p>
      )}

      <h2 className="pt-2 font-medium">{t("admin.incidents.comments")}</h2>
      <ul className="flex flex-col gap-2 text-sm" data-testid="incident-comments">
        {incident.comments.map((c) => (
          <li key={c.id} className="rounded bg-muted/50 p-2">
            <div className="text-xs text-muted-foreground">
              {c.author?.full_name ?? t("admin.incidents.system")} · {formatDateTime(c.created_at)}
            </div>
            <div className="whitespace-pre-wrap">{c.text}</div>
          </li>
        ))}
      </ul>
      {hasPermission(me, "admin.incidents.manage") && (
        <div className="flex gap-2">
          <textarea
            aria-label={t("admin.incidents.comment")}
            className="min-h-10 flex-1 rounded-md border border-border bg-background p-2 text-sm"
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
            }}
          />
          <Button
            variant="outline"
            disabled={!comment.trim() || addComment.isPending}
            onClick={() => {
              addComment.mutate();
            }}
          >
            {t("admin.incidents.addComment")}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error instanceof ApiError ? error.message : t("common.loadError")}
        </p>
      )}
    </div>
  );
}

/** Карточка инцидента (§13.5): данные по типу, жизненный цикл, ответственный, комментарии. */
export function IncidentPage() {
  const { incidentId = "" } = useParams();
  const { t } = useTranslation();
  const { data: me } = useMe();
  const incident = useQuery({
    queryKey: ["admin", "incident", incidentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/incidents/{incident_id}", {
          params: { path: { incident_id: incidentId } },
        }),
      ),
  });
  const i = incident.data;
  if (incident.isError) return <p role="alert">{t("common.loadError")}</p>;
  if (!i) return null;
  return (
    <section className="flex max-w-5xl flex-col gap-4" data-testid="incident-card">
      <Link to="/admin/incidents" className="text-sm text-muted-foreground hover:underline">
        ← {t("admin.incidents.back")}
      </Link>
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">{i.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone="muted">
            {t(`admin.incidents.types.${i.type}`, { defaultValue: i.type })}
          </Badge>
          <Badge tone={tone(SEVERITY_TONE, i.severity)}>
            {t(`admin.incidents.severities.${i.severity}`, { defaultValue: i.severity })}
          </Badge>
          <Badge tone={tone(STATUS_TONE, i.status)}>
            {t(`admin.incidents.statuses.${i.status}`, { defaultValue: i.status })}
          </Badge>
          <span className="text-muted-foreground">
            {t("admin.incidents.occurrences")}: {i.occurrences} · {t("admin.incidents.firstSeen")}{" "}
            {formatDateTime(i.first_seen)} · {t("admin.incidents.lastSeen")}{" "}
            {formatDateTime(i.last_seen)}
          </span>
        </div>
        {i.user && (
          <p className="text-sm">
            {t("admin.incidents.user")}:{" "}
            <Link to={`/admin/users/${i.user.id}`} className="hover:underline">
              {i.user.full_name}
            </Link>
            {i.chat_id && hasPermission(me, "admin.chats.view") && (
              <>
                {" · "}
                <Link
                  to={`/admin/chats/${i.chat_id}${i.message_id ? `#m-${i.message_id}` : ""}`}
                  className="text-primary underline"
                >
                  {t("admin.incidents.openChat")}
                </Link>
              </>
            )}
          </p>
        )}
      </header>
      <PayloadView incident={i} />
      {/* Ключ — только id: новые комментарии и ответ на «Сохранить» не должны сбрасывать
          несохранённый черновик и надпись «Сохранено». */}
      <Workflow key={i.id} incident={i} />
    </section>
  );
}
