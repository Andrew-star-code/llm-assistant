import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, LogIn } from "lucide-react";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router";

import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMe, useSetMe } from "@/features/auth/useMe";
import { ThemeToggle } from "@/features/theme/ThemeToggle";

type Provider = "ldap" | "dev";

function useLogin() {
  const setMe = useSetMe();
  return useMutation({
    mutationFn: async (body: { login: string; password: string; provider: Provider }) =>
      unwrap(await api.POST("/api/auth/login", { body })),
    onSuccess: (me) => {
      setMe(me);
    },
  });
}

/** Страница входа (§6.1): логин и пароль домена; в разработке — быстрый вход провайдером dev. */
export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const { data: me } = useMe();
  const providers = useQuery({
    queryKey: ["auth", "providers"],
    queryFn: async () => unwrap(await api.GET("/api/auth/providers")),
  });
  const login = useLogin();
  const [form, setForm] = useState({ login: "", password: "" });

  if (me) return <Navigate to={from} replace />;

  const submit = (provider: Provider, loginValue: string, password: string) => {
    login.mutate(
      { login: loginValue, password, provider },
      {
        onSuccess: () => {
          void navigate(from, { replace: true });
        },
      },
    );
  };

  const onSubmit = (event: SubmitEvent) => {
    event.preventDefault();
    submit("ldap", form.login, form.password);
  };

  const hasLdap = providers.data?.providers.includes("ldap") ?? false;
  const devUsers = providers.data?.providers.includes("dev")
    ? (providers.data.dev_users ?? [])
    : [];
  const error =
    login.error instanceof ApiError && login.error.status === 401
      ? t("login.invalid")
      : login.error
        ? t("login.failed")
        : null;

  return (
    <div className="flex min-h-dvh flex-col bg-muted/40 text-foreground">
      <div className="flex justify-end p-4">
        <ThemeToggle />
      </div>
      <main className="flex flex-1 items-start justify-center px-4 pt-[10vh]">
        <div className="w-full max-w-sm rounded-xl border border-border bg-background p-8 shadow-sm">
          <div className="mb-6 flex flex-col items-center gap-2 text-center">
            <Bot className="size-10 text-primary" />
            <h1 className="text-xl font-semibold">{t("app.name")}</h1>
            <p className="text-sm text-muted-foreground">{t("login.subtitle")}</p>
          </div>

          {error && (
            <p
              role="alert"
              className="mb-4 rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400"
            >
              {error}
            </p>
          )}

          {hasLdap && (
            <form className="flex flex-col gap-3" onSubmit={onSubmit}>
              <label className="flex flex-col gap-1 text-sm">
                {t("login.login")}
                <Input
                  name="login"
                  autoComplete="username"
                  autoFocus
                  required
                  placeholder="ivanov"
                  value={form.login}
                  onChange={(e) => {
                    setForm({ ...form, login: e.target.value });
                  }}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                {t("login.password")}
                <Input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={form.password}
                  onChange={(e) => {
                    setForm({ ...form, password: e.target.value });
                  }}
                />
              </label>
              <Button type="submit" disabled={login.isPending} className="mt-2">
                <LogIn />
                {t("login.submit")}
              </Button>
              <p className="text-xs text-muted-foreground">{t("login.hint")}</p>
            </form>
          )}

          {devUsers.length > 0 && (
            <section className={hasLdap ? "mt-6 border-t border-border pt-4" : ""}>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t("login.devTitle")}
              </h2>
              <ul className="flex flex-col gap-1">
                {devUsers.map((user) => (
                  <li key={user.login}>
                    <button
                      type="button"
                      data-testid={`dev-login-${user.login}`}
                      disabled={login.isPending}
                      onClick={() => {
                        submit("dev", user.login, "");
                      }}
                      className="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted"
                    >
                      <span className="font-medium">{user.full_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {[user.title, user.department].filter(Boolean).join(" · ")}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
