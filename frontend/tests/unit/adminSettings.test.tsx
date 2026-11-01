import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const MANAGER = { ...ADMIN_ME, permissions: ["admin.access", "admin.settings.manage"] };
const VALUES = {
  app_name: "Ассистент",
  company_name: "ООО «Корпорация»",
  notice_text: "Переписка сохраняется.",
  retention_days: 0,
  max_file_mb: 50,
  max_files_per_message: 10,
  default_address_form: "name_patronymic",
  system_prompt: "Ты ассистент.",
};
const SETTINGS = {
  ...VALUES,
  has_logo: false,
  logo_version: null,
  overridden: [],
  defaults: VALUES,
};

describe("Админка «Настройки»", () => {
  it("подтверждает сохранение, хотя форма пересоздаётся с новыми значениями", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(MANAGER),
      "GET /api/admin/settings": () => json(SETTINGS),
      "PUT /api/admin/settings": async (request) => {
        const body = (await request.json()) as { app_name: string };
        return json({ ...SETTINGS, app_name: body.app_name, overridden: ["app_name"] });
      },
    });
    renderApp("/admin/settings");
    const name = await screen.findByLabelText("Название в интерфейсе");
    await userEvent.clear(name);
    await userEvent.type(name, "Помощник");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Сохранено");
    // Теперь в подписи поля ещё и пометка, что значение задано в админке.
    const saved = screen.getByLabelText(/^Название в интерфейсе/);
    expect(saved).toHaveValue("Помощник");

    // Новая правка — подтверждение прошлого сохранения больше не относится к форме.
    await userEvent.type(saved, "!");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
