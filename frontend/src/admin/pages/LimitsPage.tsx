import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

type Policy = Schemas["PolicyOut"];
type PolicyIn = Schemas["PolicyIn"];
type Metric = PolicyIn["metric"];
type Window = NonNullable<PolicyIn["window"]>;
type Scope = PolicyIn["scope"];

const POLICIES = ["admin", "limit-policies"] as const;
const METRICS: Metric[] = [
  "messages",
  "tokens",
  "concurrent_generations",
  "uploads",
  "personal_kb_storage",
  "personal_kb_documents",
];
const WINDOWED = new Set<Metric>(["messages", "tokens", "uploads"]);
const QUALIFIED = new Set<Metric>(["messages", "tokens"]);
const WINDOWS: Window[] = ["minute", "hour", "day", "week", "month"];
const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";

function ErrorText({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-red-600">
      {error instanceof ApiError ? error.message : t("common.loadError")}
    </p>
  );
}

/** Ключ политики словами: «Сообщения · в день · только размышления». */
function KeyText({
  metric,
  window,
  model_role: role,
  thinking,
}: {
  metric: string;
  window: string | null;
  model_role: string | null;
  thinking: boolean;
}) {
  const { t } = useTranslation();
  const parts = [t(`limits.metric.${metric}`, { defaultValue: metric })];
  if (window) parts.push(t(`limits.window.${window}`));
  if (thinking) parts.push(t("limits.thinkingOnly"));
  if (role) parts.push(t("limits.modelOnly", { role }));
  return <>{parts.join(" · ")}</>;
}

function Target({ policy }: { policy: Policy }) {
  const { t } = useTranslation();
  if (policy.scope === "global") return <>{t("admin.limits.scopes.global")}</>;
  const target = policy.target;
  if (!target) return <>—</>;
  if (policy.scope === "user") {
    return (
      <Link to={`/admin/users/${target.id}`} className="hover:underline">
        {target.name}
      </Link>
    );
  }
  return (
    <>
      {t("admin.limits.scopes.role")}: {target.name}
    </>
  );
}

/** Редактор лимита одной политики: значение меняется без пересоздания. */
function LimitCell({ policy }: { policy: Policy }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(policy.limit));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/admin/limits/policies/{policy_id}", {
          params: { path: { policy_id: policy.id } },
          body: { limit: Number(value) },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: POLICIES }),
  });
  const changed = value !== String(policy.limit);
  return (
    <div className="flex items-center gap-1">
      <Input
        type="number"
        min={0}
        className="h-8 w-32"
        aria-label={t("admin.limits.limit")}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
        }}
      />
      {changed && (
        <Button
          size="sm"
          variant="outline"
          disabled={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          {t("common.save")}
        </Button>
      )}
    </div>
  );
}

/** «Лимиты» (§12.4, §13.2): политики — глобальные, ролевые, персональные и временные. */
export function LimitsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [expired, setExpired] = useState(false);
  const [scope, setScope] = useState<Scope>("role");
  const [roleId, setRoleId] = useState("");
  const [login, setLogin] = useState("");
  const [metric, setMetric] = useState<Metric>("messages");
  const [window, setWindow] = useState<Window>("day");
  const [limit, setLimit] = useState("");
  const [modelRole, setModelRole] = useState("");
  const [thinking, setThinking] = useState(false);
  const [expires, setExpires] = useState("");
  const [note, setNote] = useState("");

  const policies = useQuery({
    queryKey: [...POLICIES, expired],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/limits/policies", {
          params: { query: { include_expired: expired } },
        }),
      ),
  });
  const roles = useQuery({
    queryKey: ["admin", "roles"],
    queryFn: async () => unwrap(await api.GET("/api/admin/roles")),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: POLICIES });

  const create = useMutation({
    mutationFn: async () => {
      let targetId: string | null = null;
      if (scope === "role") targetId = roleId || null;
      if (scope === "user") {
        // Пользователь — по логину: точное совпадение среди найденных.
        const page = unwrap(
          await api.GET("/api/admin/users", { params: { query: { q: login.trim() } } }),
        );
        const user = page.items.find((u) => u.login === login.trim().toLowerCase());
        if (!user) throw new Error(t("admin.limits.userNotFound", { login }));
        targetId = user.id;
      }
      return unwrap(
        await api.POST("/api/admin/limits/policies", {
          body: {
            scope,
            target_id: targetId,
            metric,
            window: WINDOWED.has(metric) ? window : null,
            limit: Number(limit),
            model_role: QUALIFIED.has(metric) && modelRole ? modelRole : null,
            thinking: QUALIFIED.has(metric) && thinking,
            expires_at: expires ? new Date(expires).toISOString() : null,
            note: note || null,
          },
        }),
      );
    },
    onSuccess: () => {
      setLimit("");
      setExpires("");
      setNote("");
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/admin/limits/policies/{policy_id}", {
          params: { path: { policy_id: id } },
        }),
      );
    },
    onSuccess: () => refresh(),
  });
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    create.mutate();
  };

  const data = policies.data;
  return (
    <section className="flex max-w-6xl flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.limits")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.limits.hint")}</p>

      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">{t("admin.limits.policies")}</h2>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={expired}
            onChange={(e) => {
              setExpired(e.target.checked);
            }}
          />
          {t("admin.limits.showExpired")}
        </label>
      </div>
      <Table
        head={[
          t("admin.limits.target"),
          t("admin.limits.key"),
          t("admin.limits.limit"),
          t("admin.limits.expires"),
          t("admin.limits.note"),
          "",
        ]}
      >
        {(data?.items ?? []).map((p) => (
          <tr key={p.id} data-testid="limit-policy-row">
            <Td>
              <Target policy={p} />
            </Td>
            <Td>
              <KeyText {...p} />
            </Td>
            <Td>{p.active ? <LimitCell policy={p} /> : p.limit}</Td>
            <Td className="whitespace-nowrap">
              {p.expires_at ? formatDateTime(p.expires_at) : t("admin.limits.forever")}
              {!p.active && <Badge tone="muted">{t("admin.limits.expired")}</Badge>}
            </Td>
            <Td className="max-w-xs text-xs">
              {p.note}
              {p.created_by && <div className="text-muted-foreground">{p.created_by}</div>}
            </Td>
            <Td>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  remove.mutate(p.id);
                }}
              >
                {t("admin.limits.delete")}
              </Button>
            </Td>
          </tr>
        ))}
      </Table>
      {policies.isSuccess && data?.items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.limits.empty")}</p>
      )}
      <ErrorText error={remove.error} />

      <form
        onSubmit={submit}
        className="flex flex-col gap-3 rounded-lg border border-border p-4"
        data-testid="limit-policy-form"
      >
        <h2 className="font-medium">{t("admin.limits.new")}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t("admin.limits.scope")}
            className={SELECT}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as Scope);
            }}
          >
            {(["global", "role", "user"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`admin.limits.scopes.${s}`)}
              </option>
            ))}
          </select>
          {scope === "role" && (
            <select
              required
              aria-label={t("admin.limits.role")}
              className={SELECT}
              value={roleId}
              onChange={(e) => {
                setRoleId(e.target.value);
              }}
            >
              <option value="">{t("admin.limits.chooseRole")}</option>
              {(roles.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          )}
          {scope === "user" && (
            <Input
              required
              className="w-48"
              aria-label={t("admin.limits.login")}
              placeholder={t("admin.limits.login")}
              value={login}
              onChange={(e) => {
                setLogin(e.target.value);
              }}
            />
          )}
          <select
            aria-label={t("admin.limits.metric")}
            className={SELECT}
            value={metric}
            onChange={(e) => {
              setMetric(e.target.value as Metric);
            }}
          >
            {METRICS.map((m) => (
              <option key={m} value={m}>
                {t(`limits.metric.${m}`)}
              </option>
            ))}
          </select>
          {WINDOWED.has(metric) && (
            <select
              aria-label={t("admin.limits.window")}
              className={SELECT}
              value={window}
              onChange={(e) => {
                setWindow(e.target.value as Window);
              }}
            >
              {WINDOWS.map((w) => (
                <option key={w} value={w}>
                  {t(`limits.window.${w}`)}
                </option>
              ))}
            </select>
          )}
          <Input
            required
            type="number"
            min={0}
            className="w-40"
            aria-label={t("admin.limits.limit")}
            placeholder={t("admin.limits.limit")}
            value={limit}
            onChange={(e) => {
              setLimit(e.target.value);
            }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {QUALIFIED.has(metric) && (
            <>
              <select
                aria-label={t("admin.limits.modelRole")}
                className={SELECT}
                value={modelRole}
                onChange={(e) => {
                  setModelRole(e.target.value);
                }}
              >
                <option value="">{t("admin.limits.anyModel")}</option>
                {(data?.model_roles ?? []).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={thinking}
                  onChange={(e) => {
                    setThinking(e.target.checked);
                  }}
                />
                {t("limits.thinkingOnly")}
              </label>
            </>
          )}
          <label className="flex items-center gap-1.5">
            {t("admin.limits.expiresLabel")}
            <Input
              type="datetime-local"
              className="w-56"
              aria-label={t("admin.limits.expires")}
              value={expires}
              onChange={(e) => {
                setExpires(e.target.value);
              }}
            />
          </label>
          <Input
            className="w-64"
            aria-label={t("admin.limits.note")}
            placeholder={t("admin.limits.note")}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
          <Button type="submit" disabled={create.isPending}>
            {t("admin.limits.add")}
          </Button>
        </div>
        <ErrorText error={create.error} />
      </form>

      <h2 className="font-medium">{t("admin.limits.defaults")}</h2>
      <p className="text-sm text-muted-foreground">{t("admin.limits.defaultsHint")}</p>
      <Table head={[t("admin.limits.key"), t("admin.limits.limit")]}>
        {(data?.defaults ?? []).map((d) => (
          <tr
            key={`${d.metric}-${d.window ?? ""}-${d.model_role ?? ""}-${String(d.thinking)}`}
            data-testid="limit-default-row"
          >
            <Td>
              <KeyText {...d} />
            </Td>
            <Td>{d.limit}</Td>
          </tr>
        ))}
      </Table>
    </section>
  );
}
