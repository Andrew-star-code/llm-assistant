import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("админ: пользователи, блокировка с аудитом, журнал входов, диагностика AD", async ({
  page,
  browser,
}) => {
  // Пользователь kim входит в отдельном контексте, чтобы появилась активная сессия.
  const kimContext = await browser.newContext();
  const kim = await kimContext.newPage();
  await devLogin(kim, "kim");

  await devLogin(page, "ivanov");
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Админка" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);

  await page.getByLabel("Поиск по ФИО, логину, отделу или должности").fill("Ким");
  await page.getByRole("link", { name: "Ким Александр" }).click();
  await expect(page.getByRole("heading", { name: "Ким Александр" })).toBeVisible();

  await page.getByLabel("Причина блокировки").fill("Проверка e2e");
  await page.getByRole("button", { name: "Заблокировать" }).click();
  await expect(page.getByText("Проверка e2e")).toBeVisible();

  // Сессия kim завершена: его следующий запрос уводит на вход.
  await kim.reload();
  await expect(kim).toHaveURL(/\/login$/);

  await page.getByRole("button", { name: "Разблокировать" }).click();
  await expect(page.getByRole("button", { name: "Заблокировать" })).toBeVisible();

  await page.getByRole("link", { name: "Журнал аудита" }).click();
  await expect(page.getByText("Разблокировка пользователя").first()).toBeVisible();
  await expect(page.getByText("Блокировка пользователя").first()).toBeVisible();

  await page.getByRole("link", { name: "Входы" }).click();
  await expect(page.getByRole("cell", { name: "kim" }).first()).toBeVisible();

  await page.getByRole("link", { name: "Диагностика AD" }).click();
  await page.getByLabel("Логин").fill("kim");
  await page.getByRole("button", { name: "Проверить" }).click();
  const report = page.getByTestId("ad-report");
  await expect(report).toContainText("Вход возможен");
  await expect(report).toContainText("Отдел: ИТ-отдел");

  await kimContext.close();
});
