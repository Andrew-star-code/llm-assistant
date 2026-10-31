import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageSquare } from "lucide-react";
import { useState, type ReactNode, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatView } from "@/features/chat/ChatPage";
import { scenarioKeys } from "@/features/scenarios/api";
import { ScenarioIcon } from "@/features/scenarios/icons";

type Spec = Required<Schemas["ScenarioSpec"]>;

const EMPTY: Spec = {
  code: "",
  name: "",
  description: null,
  icon: "sparkles",
  roles: [],
  model_role: "chat",
  prompt_template: "",
  tools: null,
  knowledge_bases: [],
  rag_mode: "auto",
  requires_attachment: false,
  attachment_hint: null,
  starter_prompts: [],
  thinking_default: null,
  is_active: true,
  sort_order: 0,
};

const SELECT = "h-9 rounded-md border border-border bg-background px-2 text-sm";

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...list, value] : list.filter((v) => v !== value);
}

/** Редактор сценария (§13.2) с тестовым чатом: изменения действуют без перезапуска. */
export function ScenarioEditorPage() {
  const { scenarioId } = useParams();
  const isNew = !scenarioId || scenarioId === "new";
  const current = useQuery({
    queryKey: [...scenarioKeys.admin, scenarioId],
    enabled: !isNew,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/scenarios/{scenario_id}", {
          params: { path: { scenario_id: scenarioId ?? "" } },
        }),
      ),
  });
  if (!isNew && !current.data) return null;
  const initial = current.data
    ? (Object.fromEntries(
        Object.keys(EMPTY).map((key) => [key, current.data[key as keyof Spec]]),
      ) as Spec)
    : EMPTY;
  return (
    <ScenarioForm
      key={scenarioId ?? "new"}
      scenarioId={isNew ? null : scenarioId}
      initial={initial}
    />
  );
}

function ScenarioForm({ scenarioId, initial }: { scenarioId: string | null; initial: Spec }) {
  const { t } = useTranslation();
  const isNew = scenarioId === null;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [spec, setSpec] = useState<Spec>(initial);
  const [testChatId, setTestChatId] = useState<string | null>(null);
  const location = useLocation();
  // После создания форма монтируется заново по адресу сценария — «Сохранено» приходит в state.
  const [saved, setSaved] = useState(
    Boolean((location.state as { saved?: boolean } | null)?.saved),
  );

  const options = useQuery({
    queryKey: scenarioKeys.options,
    queryFn: async () => unwrap(await api.GET("/api/admin/scenarios/options")),
  });

  const set = <K extends keyof Spec>(key: K, value: Spec[K]) => {
    setSpec((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const save = useMutation({
    mutationFn: async () =>
      isNew
        ? unwrap(await api.POST("/api/admin/scenarios", { body: spec }))
        : unwrap(
            await api.PUT("/api/admin/scenarios/{scenario_id}", {
              params: { path: { scenario_id: scenarioId } },
              body: spec,
            }),
          ),
    onSuccess: async (result) => {
      setSaved(true);
      await queryClient.invalidateQueries({ queryKey: scenarioKeys.admin });
      await queryClient.invalidateQueries({ queryKey: scenarioKeys.list });
      if (isNew) {
        void navigate(`/admin/scenarios/${result.id}`, { replace: true, state: { saved: true } });
      }
    },
  });
  const remove = useMutation({
    mutationFn: async () => {
      unwrap(
        await api.DELETE("/api/admin/scenarios/{scenario_id}", {
          params: { path: { scenario_id: scenarioId ?? "" } },
        }),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: scenarioKeys.admin });
      void navigate("/admin/scenarios");
    },
  });
  const startTest = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/scenarios/{scenario_id}/test-chat", {
          params: { path: { scenario_id: scenarioId ?? "" } },
        }),
      ),
    onSuccess: (result) => {
      setTestChatId(result.chat_id);
    },
  });

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const opts = options.data;
  const unknownRoles = spec.roles.filter((r) => !opts?.roles.some((o) => o.code === r));

  return (
    <section className="flex flex-col gap-4">
      <Link
        to="/admin/scenarios"
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground"
      >
        <ArrowLeft className="size-4" /> {t("admin.nav.scenarios")}
      </Link>
      <h1 className="text-xl font-semibold">
        {isNew ? t("admin.scenarios.new") : spec.name || "…"}
      </h1>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form onSubmit={submit} className="flex flex-col gap-4" data-testid="scenario-form">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("admin.scenarios.name")}>
              <Input
                required
                value={spec.name}
                onChange={(e) => {
                  set("name", e.target.value);
                }}
              />
            </Field>
            <Field label={t("admin.scenarios.code")}>
              <Input
                required
                pattern="[a-z0-9][a-z0-9_\-]*"
                value={spec.code}
                onChange={(e) => {
                  set("code", e.target.value);
                }}
              />
            </Field>
          </div>
          <Field label={t("admin.scenarios.description")}>
            <Input
              value={spec.description ?? ""}
              onChange={(e) => {
                set("description", e.target.value || null);
              }}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t("admin.scenarios.icon")}>
              <span className="flex items-center gap-2">
                <ScenarioIcon name={spec.icon ?? null} className="size-5 text-primary" />
                <select
                  className={SELECT}
                  value={spec.icon ?? ""}
                  onChange={(e) => {
                    set("icon", e.target.value);
                  }}
                >
                  {(opts?.icons ?? []).map((icon) => (
                    <option key={icon} value={icon}>
                      {icon}
                    </option>
                  ))}
                </select>
              </span>
            </Field>
            <Field label={t("admin.scenarios.model")}>
              <select
                className={SELECT}
                value={spec.model_role}
                onChange={(e) => {
                  set("model_role", e.target.value);
                }}
              >
                {(opts?.model_roles ?? [spec.model_role]).map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("admin.scenarios.thinking")}>
              <select
                className={SELECT}
                value={spec.thinking_default === null ? "model" : String(spec.thinking_default)}
                onChange={(e) => {
                  const v = e.target.value;
                  set("thinking_default", v === "model" ? null : v === "true");
                }}
              >
                <option value="model">{t("admin.scenarios.thinkingModel")}</option>
                <option value="true">{t("admin.scenarios.thinkingOn")}</option>
                <option value="false">{t("admin.scenarios.thinkingOff")}</option>
              </select>
            </Field>
          </div>
          <Field
            label={t("admin.scenarios.prompt")}
            hint={t("admin.scenarios.variables", {
              list: Object.keys(opts?.variables ?? {})
                .map((v) => `{{ ${v} }}`)
                .join(", "),
            })}
          >
            <textarea
              className="min-h-56 rounded-md border border-border bg-background p-2 font-mono text-xs"
              value={spec.prompt_template}
              data-testid="scenario-prompt"
              onChange={(e) => {
                set("prompt_template", e.target.value);
              }}
            />
          </Field>
          <Field label={t("admin.scenarios.ragMode")}>
            <select
              className={`${SELECT} w-fit`}
              value={spec.rag_mode}
              onChange={(e) => {
                set("rag_mode", e.target.value as Spec["rag_mode"]);
              }}
            >
              {(opts?.rag_modes ?? ["auto", "tool", "off"]).map((m) => (
                <option key={m} value={m}>
                  {t(`admin.scenarios.ragModes.${m}`)}
                </option>
              ))}
            </select>
          </Field>
          <fieldset className="flex flex-col gap-1 text-sm">
            <legend className="mb-1 font-medium">{t("admin.scenarios.knowledgeBases")}</legend>
            <span className="text-xs text-muted-foreground">{t("admin.scenarios.kbHint")}</span>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {(opts?.knowledge_bases ?? []).map((kb) => (
                <label key={kb.code} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={spec.knowledge_bases.includes(kb.code)}
                    onChange={(e) => {
                      set(
                        "knowledge_bases",
                        toggle(spec.knowledge_bases, kb.code, e.target.checked),
                      );
                    }}
                  />
                  {kb.name}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-1 text-sm">
            <legend className="mb-1 font-medium">{t("admin.scenarios.tools")}</legend>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={spec.tools === null}
                onChange={(e) => {
                  set("tools", e.target.checked ? null : []);
                }}
              />
              {t("admin.scenarios.allTools")}
            </label>
            {spec.tools && (
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {(opts?.tools ?? []).map((tool) => (
                  <label key={tool} className="flex items-center gap-1.5 font-mono text-xs">
                    <input
                      type="checkbox"
                      checked={(spec.tools ?? []).includes(tool)}
                      onChange={(e) => {
                        set("tools", toggle(spec.tools ?? [], tool, e.target.checked));
                      }}
                    />
                    {tool}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-1 text-sm">
            <legend className="mb-1 font-medium">{t("admin.scenarios.roles")}</legend>
            <span className="text-xs text-muted-foreground">{t("admin.scenarios.rolesHint")}</span>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {(opts?.roles ?? []).map((role) => (
                <label key={role.code} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={spec.roles.includes(role.code)}
                    onChange={(e) => {
                      set("roles", toggle(spec.roles, role.code, e.target.checked));
                    }}
                  />
                  {role.name}
                </label>
              ))}
              {unknownRoles.map((code) => (
                <label key={code} className="flex items-center gap-1.5 text-muted-foreground">
                  <input
                    type="checkbox"
                    checked
                    onChange={() => {
                      set("roles", toggle(spec.roles, code, false));
                    }}
                  />
                  {code} ({t("admin.scenarios.roleMissing")})
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={spec.requires_attachment}
                onChange={(e) => {
                  set("requires_attachment", e.target.checked);
                }}
              />
              {t("admin.scenarios.requiresAttachment")}
            </label>
            <Input
              placeholder={t("admin.scenarios.attachmentHint")}
              aria-label={t("admin.scenarios.attachmentHint")}
              value={spec.attachment_hint ?? ""}
              disabled={!spec.requires_attachment}
              onChange={(e) => {
                set("attachment_hint", e.target.value || null);
              }}
            />
          </div>
          <Field label={t("admin.scenarios.starters")} hint={t("admin.scenarios.startersHint")}>
            <textarea
              className="min-h-20 rounded-md border border-border bg-background p-2 text-sm"
              value={spec.starter_prompts.join("\n")}
              onChange={(e) => {
                set(
                  "starter_prompts",
                  e.target.value
                    .split("\n")
                    .map((line) => line.trimStart())
                    .filter((line, i, all) => line || i === all.length - 1),
                );
              }}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={spec.is_active}
                onChange={(e) => {
                  set("is_active", e.target.checked);
                }}
              />
              {t("admin.scenarios.active")}
            </label>
            <label className="flex items-center gap-2">
              {t("admin.scenarios.order")}
              <Input
                type="number"
                className="w-20"
                value={spec.sort_order}
                onChange={(e) => {
                  set("sort_order", Number(e.target.value));
                }}
              />
            </label>
          </div>
          {save.isError && (
            <p role="alert" className="text-sm text-red-600" data-testid="scenario-error">
              {save.error instanceof ApiError ? save.error.message : t("common.loadError")}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={save.isPending} data-testid="scenario-save">
              {t("admin.scenarios.save")}
            </Button>
            {saved && (
              <span className="text-sm text-emerald-600" data-testid="scenario-saved">
                {t("admin.scenarios.saved")}
              </span>
            )}
            {!isNew && (
              <Button
                variant="outline"
                className="ml-auto text-red-600"
                onClick={() => {
                  if (window.confirm(t("admin.scenarios.confirmDelete"))) remove.mutate();
                }}
              >
                {t("admin.scenarios.delete")}
              </Button>
            )}
          </div>
        </form>

        <aside
          className="flex min-h-[32rem] flex-col rounded-lg border border-border"
          data-testid="test-chat"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="text-sm font-medium">{t("admin.scenarios.testChat")}</span>
            <Button
              size="sm"
              variant="outline"
              disabled={isNew || startTest.isPending}
              onClick={() => {
                startTest.mutate();
              }}
            >
              <MessageSquare className="size-4" />
              {testChatId ? t("admin.scenarios.restartTest") : t("admin.scenarios.startTest")}
            </Button>
          </div>
          {testChatId ? (
            <div className="h-[36rem] min-h-0">
              <ChatView key={testChatId} chatId={testChatId} embedded />
            </div>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">
              {isNew ? t("admin.scenarios.saveFirst") : t("admin.scenarios.testHint")}
            </p>
          )}
        </aside>
      </div>
    </section>
  );
}
