import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("админ находит сообщение по слову, открывает чат, просмотр — в аудите; выгрузка XLSX", async ({
  browser,
}) => {
  // Пользователь пишет сообщение с уникальным кодом.
  const code = `ZEBRA${String(Date.now()).slice(-6)}`;
  const user = await browser.newPage();
  await devLogin(user, "petrov");
  await user.goto("/");
  await user.getByTestId("composer-input").fill(`Квартальный отчёт по договору ${code}`);
  await user.getByTestId("send-button").click();
  await expect(user).toHaveURL(/\/c\/[0-9a-f-]+$/);
  await expect(user.getByTestId("assistant-message").last()).not.toBeEmpty();

  const admin = await browser.newPage();
  await devLogin(admin, "ivanov");
  await admin.goto("/admin");
  await expect(admin).toHaveURL(/\/admin\/dashboard$/);
  await expect(admin.getByTestId("dashboard-active")).toBeVisible();

  await admin.getByRole("link", { name: "Переписка" }).click();
  await admin.getByTestId("admin-chat-search").fill(code);
  await admin.getByRole("button", { name: "Поиск" }).click();
  const hit = admin.getByTestId("admin-message-hit").filter({ hasText: "Петров" }).first();
  await expect(hit.locator("mark")).toContainText(code);
  await hit.getByRole("link").click();
  await expect(admin.getByTestId("admin-chat")).toContainText(
    `Квартальный отчёт по договору ${code}`,
  );
  await expect(admin.getByText("Просмотр записан в журнал аудита")).toBeVisible();

  // Выгрузка этого чата в XLSX — в разделе «Выгрузки» появляется готовый файл.
  await admin.getByLabel("Формат выгрузки").selectOption("xlsx");
  await admin.getByRole("button", { name: "Выгрузить" }).click();
  await admin.getByRole("link", { name: /Выгрузка заказана/ }).click();
  const row = admin.getByTestId("export-row").first();
  await expect(row).toContainText("готова", { timeout: 30_000 });
  const download = admin.waitForEvent("download");
  await row.getByRole("link", { name: "Скачать" }).click();
  expect((await download).suggestedFilename()).toMatch(/^Выгрузка переписки .+\.xlsx$/);

  await admin.getByRole("link", { name: "Журнал аудита" }).click();
  await expect(admin.getByRole("cell", { name: "Просмотр чата" }).first()).toBeVisible();
  await expect(admin.getByRole("cell", { name: "Скачивание выгрузки" }).first()).toBeVisible();
});

test("админ: обратная связь, модели, инструменты и настройки открываются", async ({ page }) => {
  await devLogin(page, "ivanov");
  await page.goto("/admin/feedback");
  await expect(page.getByTestId("feedback-summary")).toBeVisible();
  await page.getByRole("link", { name: "Модели" }).click();
  await expect(page.getByTestId("model-row").filter({ hasText: "chat" }).first()).toBeVisible();
  await page.getByRole("link", { name: "Инструменты" }).click();
  await expect(page.getByTestId("tool-row").filter({ hasText: "create_document" })).toBeVisible();
  await page.getByRole("link", { name: "Настройки" }).click();
  await expect(page.getByTestId("settings-form")).toBeVisible();
  // Ошибка в шаблоне системного промпта — понятное сообщение, ничего не сохраняется.
  await page.getByTestId("settings-system-prompt").fill("{{ company");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("settings-error")).toContainText("Ошибка в шаблоне промпта");
});
