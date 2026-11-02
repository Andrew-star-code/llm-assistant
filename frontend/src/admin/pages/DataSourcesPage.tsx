import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

type Fn = Record<string, unknown> & {
  name: string;
  description: string;
  params: Record<string, { type?: string; required?: boolean; description?: string }>;
  sql?: string;
  roles?: string[];
};
type Ds = Record<string, unknown> & {
  name: string;
  title: string;
  description: string;
  view?: string;
  source?: string;
  roles?: string[];
  columns?: number;
  rls?: { column: string; equals: string; unless_roles?: string[] }[];
};

/** Ячейка результата: значения шлюза — строки, числа, булевы и null. */
function cellText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

const PRE = "max-h-60 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap";

function roleList(roles: string[] | undefined, everyone: string): string {
  return roles?.length ? roles.join(", ") : everyone;
}

/** Тестовый вызов функции от имени админа: параметры — по описанию из каталога. */
function TestCall({ fn }: { fn: Fn }) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const call = useMutation({
    mutationFn: async () => {
      const params = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== ""));
      return unwrap(
        await api.POST("/api/admin/data/functions/{name}/test", {
          params: { path: { name: fn.name } },
          body: { params },
        }),
      );
    },
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    call.mutate();
  };
  const result: Schemas["TestCallOut"] | undefined = call.data;
  return (
    <form onSubmit={submit} className="flex flex-col gap-2" data-testid={`test-${fn.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(fn.params).map(([name, spec]) => (
          <Input
            key={name}
            className="w-48"
            aria-label={name}
            placeholder={`${name}${spec.required === false ? "" : " *"}`}
            title={spec.description}
            value={values[name] ?? ""}
            onChange={(e) => {
              setValues((v) => ({ ...v, [name]: e.target.value }));
            }}
          />
        ))}
        <Button type="submit" size="sm" disabled={call.isPending}>
          {t("admin.data.run")}
        </Button>
      </div>
      {call.error && (
        <p role="alert" className="text-sm text-red-600">
          {call.error instanceof ApiError ? call.error.message : t("common.loadError")}
        </p>
      )}
      {result && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">
            {t("admin.data.resultSummary", {
              rows: result.row_count,
              ms: result.duration_ms,
            })}
          </p>
          <Table head={result.columns}>
            {result.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <Td key={j}>{cellText(cell)}</Td>
                ))}
              </tr>
            ))}
          </Table>
        </div>
      )}
    </form>
  );
}

/** «Источники данных» (§13.2): каталог семантического слоя, тестовый вызов, журнал запросов. */
export function DataSourcesPage() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const catalog = useQuery({
    queryKey: ["admin", "data-catalog"],
    queryFn: async () => unwrap(await api.GET("/api/admin/data/catalog")),
  });
  const journal = useInfiniteQuery({
    queryKey: ["admin", "data-queries", q],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/admin/data/queries", {
          params: { query: { q: q || null, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor,
  });
  const data = catalog.data;
  const datasets = (data?.datasets ?? []) as Ds[];
  const functions = (data?.functions ?? []) as Fn[];
  const entries = journal.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="flex max-w-6xl flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.data")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.data.hint")}</p>
      {data && !data.configured && (
        <p role="status" className="text-sm">
          {t("admin.data.notConfigured")}
        </p>
      )}
      {data?.error && (
        <p role="alert" className="text-sm text-red-600">
          {data.error_code === "unavailable"
            ? t("admin.data.unavailable")
            : t("admin.data.gatewayError", { error: data.error })}
        </p>
      )}
      {data?.catalog_error && (
        <p role="alert" className="text-sm text-red-600" data-testid="catalog-error">
          {t("admin.data.catalogError", { error: data.catalog_error })}
        </p>
      )}

      {datasets.length > 0 && (
        <>
          <h2 className="font-medium">{t("admin.data.datasets")}</h2>
          <Table
            head={[
              t("admin.data.dataset"),
              t("admin.data.view"),
              t("admin.data.roles"),
              t("admin.data.rls"),
            ]}
          >
            {datasets.map((d) => (
              <tr key={d.name} data-testid="dataset-row">
                <Td>
                  <div className="font-medium">{d.title}</div>
                  <div className="text-xs text-muted-foreground">
                    <code>{d.name}</code> · {d.description}
                  </div>
                </Td>
                <Td>
                  <code>{d.view}</code>
                  <div className="text-xs text-muted-foreground">
                    {d.source} · {t("admin.data.columns", { count: d.columns ?? 0 })}
                  </div>
                </Td>
                <Td className="text-xs">{roleList(d.roles, t("admin.data.everyone"))}</Td>
                <Td className="text-xs">
                  {d.rls?.length
                    ? d.rls.map((r) => (
                        <div key={r.column}>
                          <code>
                            {r.column} = {r.equals}
                          </code>
                          {r.unless_roles?.length
                            ? ` · ${t("admin.data.except", { roles: r.unless_roles.join(", ") })}`
                            : ""}
                        </div>
                      ))
                    : "—"}
                </Td>
              </tr>
            ))}
          </Table>
        </>
      )}

      {functions.length > 0 && (
        <>
          <h2 className="font-medium">{t("admin.data.functions")}</h2>
          <div className="flex flex-col gap-3">
            {functions.map((f) => (
              <div
                key={f.name}
                className="flex flex-col gap-2 rounded-lg border border-border p-3"
                data-testid="function-card"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <code className="font-medium">{f.name}</code>
                  <Badge tone="muted">{roleList(f.roles, t("admin.data.everyone"))}</Badge>
                </div>
                <p className="text-sm">{f.description}</p>
                {f.sql && <pre className={PRE}>{f.sql}</pre>}
                <TestCall fn={f} />
              </div>
            ))}
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium">{t("admin.data.journal")}</h2>
        <Input
          className="w-72"
          aria-label={t("admin.data.search")}
          placeholder={t("admin.data.search")}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
          }}
        />
      </div>
      <Table
        head={[
          t("admin.data.time"),
          t("admin.data.user"),
          t("admin.data.query"),
          t("admin.data.result"),
        ]}
      >
        {entries.map((e) => (
          <tr key={e.id} data-testid="query-row">
            <Td className="whitespace-nowrap">{formatDateTime(e.ts)}</Td>
            <Td>{e.user ?? "—"}</Td>
            <Td className="max-w-xl">
              <div className="text-xs text-muted-foreground">
                {e.action === "data.function" ? t("admin.data.function") : t("admin.data.sql")}
                {e.target ? ` · ${e.target}` : ""}
              </div>
              {e.sql && <pre className={PRE}>{e.sql}</pre>}
              {e.error && <div className="text-xs text-red-600">{e.error}</div>}
            </Td>
            <Td className="text-xs whitespace-nowrap">
              <Badge tone={e.status === "ok" ? "ok" : "bad"}>
                {t(`admin.data.statuses.${e.status ?? "error"}`, { defaultValue: e.status ?? "" })}
              </Badge>
              {e.rows !== null && <div>{t("admin.data.rows", { count: e.rows })}</div>}
              {e.duration_ms !== null && <div>{e.duration_ms} мс</div>}
              {e.chat_id && (
                <Link to={`/admin/chats/${e.chat_id}`} className="text-primary underline">
                  {t("admin.data.chat")}
                </Link>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      {journal.isSuccess && entries.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.data.empty")}</p>
      )}
      {journal.hasNextPage && (
        <Button
          variant="outline"
          className="w-fit"
          onClick={() => {
            void journal.fetchNextPage();
          }}
        >
          {t("common.loadMore")}
        </Button>
      )}
    </section>
  );
}
