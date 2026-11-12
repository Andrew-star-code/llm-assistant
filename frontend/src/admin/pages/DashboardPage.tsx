import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { BarChart } from "@/admin/components/BarChart";
import { Card, Stat } from "@/admin/components/Card";
import { Badge } from "@/admin/components/Table";
import { api, unwrap } from "@/api/client";

const percent = (share: number | null | undefined) =>
  share === null || share === undefined ? "—" : `${String(Math.round(share * 1000) / 10)}%`;

/** Дашборд (§13.2): активность, токены, время ответа, качество, модели, очереди, GPU. */
export function DashboardPage() {
  const { t } = useTranslation();
  const board = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/admin/dashboard")),
    refetchInterval: 60_000,
  });
  const d = board.data;
  const ms = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : t("admin.dashboard.ms", { value: v });
  const day = (iso: string) => iso.slice(8, 10) + "." + iso.slice(5, 7);

  return (
    <section className="flex flex-col gap-4" data-testid="dashboard">
      <h1 className="text-xl font-semibold">{t("admin.nav.dashboard")}</h1>
      {board.isError && <p role="alert">{t("common.loadError")}</p>}
      {d && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Card title={t("admin.dashboard.activeUsers")} testId="dashboard-active">
              <div className="flex gap-6">
                <Stat label={t("admin.dashboard.day")} value={d.active_users.day} />
                <Stat label={t("admin.dashboard.week")} value={d.active_users.week} />
                <Stat label={t("admin.dashboard.month")} value={d.active_users.month} />
              </div>
            </Card>
            <Card title={t("admin.dashboard.quality", { days: d.days })}>
              <div className="flex flex-wrap gap-6">
                <Stat label={t("admin.dashboard.answers")} value={d.quality.answers} />
                <Stat
                  label={t("admin.dashboard.errorShare")}
                  value={percent(d.quality.error_share)}
                />
                <Stat
                  label={t("admin.dashboard.likeShare")}
                  value={percent(d.quality.like_share)}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {t("admin.dashboard.likes")}: {d.quality.likes} · {t("admin.dashboard.dislikes")}:{" "}
                {d.quality.dislikes}
              </p>
            </Card>
            <Card title={t("admin.dashboard.ttft")}>
              <div className="flex gap-6">
                <Stat label={t("admin.dashboard.avg")} value={ms(d.quality.ttft_avg_ms)} />
                <Stat label={t("admin.dashboard.p95")} value={ms(d.quality.ttft_p95_ms)} />
              </div>
            </Card>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card title={t("admin.dashboard.messages")}>
              <BarChart
                label={t("admin.dashboard.messages")}
                points={d.series.map((p) => ({ key: p.day, value: p.messages, title: day(p.day) }))}
              />
            </Card>
            <Card title={t("admin.dashboard.tokens")}>
              <BarChart
                label={t("admin.dashboard.tokens")}
                points={d.series.map((p) => ({ key: p.day, value: p.tokens, title: day(p.day) }))}
                format={(v) => v.toLocaleString("ru-RU")}
              />
            </Card>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Card title={t("admin.dashboard.models")} testId="dashboard-models">
              <ul className="flex flex-col gap-1 text-sm">
                {d.models.map((m) => (
                  <li key={m.role} className="flex items-center justify-between gap-2">
                    <span>{m.role}</span>
                    <Badge tone={m.ok ? "ok" : "bad"}>
                      {m.ok ? t("admin.dashboard.ok") : t("admin.dashboard.down")}
                      {m.ok && m.latency_ms !== null ? ` · ${ms(m.latency_ms)}` : ""}
                    </Badge>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title={t("admin.dashboard.queues")}>
              <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
                <dt>{t("admin.dashboard.kbQueued")}</dt>
                <dd className="tabular-nums">{d.queues.kb_queued}</dd>
                <dt>{t("admin.dashboard.kbProcessing")}</dt>
                <dd className="tabular-nums">{d.queues.kb_processing}</dd>
                <dt>{t("admin.dashboard.kbErrors")}</dt>
                <dd className="tabular-nums">{d.queues.kb_errors}</dd>
                <dt>{t("admin.dashboard.imports")}</dt>
                <dd className="tabular-nums">{d.queues.imports_running}</dd>
                <dt>{t("admin.dashboard.attachments")}</dt>
                <dd className="tabular-nums">{d.queues.attachments_pending}</dd>
                {typeof d.queues.generation_queued === "number" && (
                  <>
                    <dt>{t("admin.dashboard.generationQueued")}</dt>
                    <dd className="tabular-nums" data-testid="generation-queued">
                      {d.queues.generation_queued}
                    </dd>
                    <dt>{t("admin.dashboard.generationExecutors")}</dt>
                    <dd
                      className={
                        d.queues.generation_executors === 0
                          ? "font-medium tabular-nums text-destructive"
                          : "tabular-nums"
                      }
                      data-testid="generation-executors"
                    >
                      {d.queues.generation_executors}
                    </dd>
                  </>
                )}
              </dl>
            </Card>
            <Card title={t("admin.dashboard.incidents")}>
              <Stat
                label={t("admin.dashboard.incidentsHigh", { count: d.incidents.high })}
                value={d.incidents.open}
              />
            </Card>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card title={t("admin.dashboard.scenarios")}>
              {d.scenarios.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("admin.dashboard.noScenarios")}</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {d.scenarios.map((s) => (
                    <li key={s.name} className="flex justify-between gap-2">
                      <span>{s.name}</span>
                      <span className="text-muted-foreground">
                        {t("admin.dashboard.chats", { count: s.chats })} ·{" "}
                        {t("admin.dashboard.msgs", { count: s.messages })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title={t("admin.dashboard.gpu")}>
              {d.gpus ? (
                <ul className="flex flex-col gap-1 text-sm">
                  {d.gpus.map((g) => (
                    <li key={g.gpu} className="flex justify-between gap-2">
                      <span>GPU {g.gpu}</span>
                      <span className="text-muted-foreground">
                        {t("admin.dashboard.gpuUtil", { value: g.utilization ?? "—" })}
                        {g.memory_used_mb !== null && g.memory_total_mb !== null
                          ? ` · ${t("admin.dashboard.gpuMemory", {
                              used: Math.round(g.memory_used_mb / 1024),
                              total: Math.round(g.memory_total_mb / 1024),
                            })}`
                          : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {d.gpu_note ?? t("admin.dashboard.noData")}
                </p>
              )}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}
