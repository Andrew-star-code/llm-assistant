import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type Schemas } from "@/api/client";
import { Avatar } from "@/components/ui/avatar";
import { ME_QUERY_KEY } from "@/features/auth/useMe";
import { LimitsSection } from "@/features/limits/LimitsSection";

type AddressForm = Schemas["Profile"]["address_form"];
const FORMS: AddressForm[] = ["name_patronymic", "first_name", "full_name", "formal"];
const PROFILE_QUERY_KEY = ["profile"] as const;

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

/** Профиль (§6.5): данные из AD, роли, форма обращения, расход лимитов (§12.4). */
export function ProfilePage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: PROFILE_QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/profile")),
  });
  const [choice, setChoice] = useState<AddressForm | null>(null);
  const update = useMutation({
    mutationFn: async (addressForm: AddressForm | null) =>
      unwrap(await api.PATCH("/api/profile/settings", { body: { address_form: addressForm } })),
    onSuccess: (data) => {
      queryClient.setQueryData(PROFILE_QUERY_KEY, data);
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });

  if (profile.isPending) return <p className="p-6 text-muted-foreground">{t("common.loading")}</p>;
  if (profile.isError) return <p className="p-6 text-red-600">{t("common.loadError")}</p>;
  const p = profile.data;
  // Выбор показываем сразу (оптимистично), пока сервер его сохраняет.
  const selected = choice ?? p.address_form;

  return (
    <section className="mx-auto flex h-full max-w-3xl flex-col gap-8 overflow-y-auto px-6 py-10">
      <header className="flex items-center gap-4">
        <Avatar
          name={p.full_name}
          src={p.has_photo ? "/api/profile/photo" : null}
          className="size-20 text-xl"
        />
        <div>
          <h1 className="text-2xl font-semibold" data-testid="profile-name">
            {p.full_name}
          </h1>
          <p className="text-muted-foreground">
            {[p.title, p.department].filter(Boolean).join(" · ")}
          </p>
        </div>
      </header>

      <dl className="divide-y divide-border rounded-lg border border-border px-4">
        <Field label={t("profile.company")} value={p.company} />
        <Field label={t("profile.office")} value={p.office} />
        <Field label={t("profile.email")} value={p.email} />
        <Field label={t("profile.phone")} value={p.phone} />
        <Field label={t("profile.mobile")} value={p.mobile} />
        <Field label={t("profile.manager")} value={p.manager_name} />
        <Field label={t("profile.login")} value={p.login} />
      </dl>

      <section>
        <h2 className="mb-3 font-semibold">{t("profile.roles")}</h2>
        <ul className="flex flex-wrap gap-2">
          {p.roles.map((role) => (
            <li
              key={`${role.code}-${role.source}`}
              className="rounded-full border border-border px-3 py-1 text-xs"
              title={t(`roleSource.${role.source}`, { defaultValue: role.source })}
            >
              {role.name}
            </li>
          ))}
          {p.roles.length === 0 && <li className="text-sm text-muted-foreground">—</li>}
        </ul>
      </section>

      <section>
        <h2 className="mb-1 font-semibold">{t("profile.addressForm")}</h2>
        <p className="mb-3 text-sm text-muted-foreground">{t("profile.addressFormHint")}</p>
        <div
          role="radiogroup"
          aria-label={t("profile.addressForm")}
          className="flex flex-col gap-2"
        >
          {FORMS.map((form) => (
            <label key={form} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="address_form"
                checked={selected === form}
                disabled={update.isPending}
                onChange={() => {
                  setChoice(form);
                  update.mutate(form, {
                    onSettled: () => {
                      setChoice(null);
                    },
                  });
                }}
              />
              {t(`addressForm.${form}`)}
            </label>
          ))}
        </div>
        <p className="mt-3 text-sm" data-testid="address-preview">
          {t("profile.addressPreview")}:{" "}
          <strong>{p.address ?? t("addressForm.formalPreview")}</strong>
        </p>
      </section>

      <LimitsSection />
    </section>
  );
}
