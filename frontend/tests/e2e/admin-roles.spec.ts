import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("админ создаёт роль и массово добавляет сотрудников списком", async ({ browser, page }) => {
  // Сотрудники должны быть в системе: дев-провайдер заводит их при первом входе.
  for (const login of ["petrov", "kim"]) {
    const user = await browser.newPage();
    await devLogin(user, login);
    await user.close();
  }
  await devLogin(page, "ivanov");
  await page.goto("/admin/roles");
  const code = `e2e${String(Date.now()).slice(-7)}`;
  const form = page.getByTestId("role-create-form");
  await form.getByLabel("Роль").fill(`Тестовая ${code}`);
  await form.getByLabel("Код (латиница)").fill(code);
  await form.getByRole("button", { name: "Создать" }).click();
  await expect(page).toHaveURL(/\/admin\/roles\/[0-9a-f-]+$/);

  await page.getByTestId("bulk-input").fill("petrov\nkim\nnobody-x");
  await page.getByRole("button", { name: "Добавить (3)" }).click();
  await expect(page.getByTestId("bulk-result")).toContainText("Добавлено: 2");
  await expect(page.getByTestId("bulk-result")).toContainText("nobody-x");
  await expect(page.getByTestId("role-member")).toHaveCount(2);

  // Убрать одного, затем удалить роль целиком.
  await page.getByRole("checkbox", { name: /Ким/ }).check();
  await page.getByRole("button", { name: "Убрать из роли (1)" }).click();
  await expect(page.getByTestId("role-member")).toHaveCount(1);
  await page.getByRole("button", { name: "Удалить роль" }).click();
  await expect(page).toHaveURL(/\/admin\/roles$/);
  await expect(page.getByTestId("role-row").filter({ hasText: code })).toHaveCount(0);
});
