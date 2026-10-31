import { expect, test } from "@playwright/test";

import { acceptNotice, devLogin } from "./helpers";

test("вход через AD: неверный пароль, затем верный; профиль из AD; выход", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Логин").fill("CORP\\sidorova");
  await page.getByLabel("Пароль").fill("wrong-password");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("alert")).toHaveText("Неверный логин или пароль");

  await page.getByLabel("Пароль").fill("Passw0rd!");
  await page.getByRole("button", { name: "Войти" }).click();
  await acceptNotice(page);
  await expect(page.getByTestId("greeting")).toContainText("Елена Николаевна!");

  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Профиль" }).click();
  await expect(page.getByTestId("profile-name")).toHaveText("Сидорова Елена Николаевна");
  await expect(page.getByText("Юрисконсульт · Юридический отдел")).toBeVisible();
  await expect(page.getByText("Отдел: Юридический отдел")).toBeVisible();
  await expect(page.getByText("+7 (495) 100-30-01")).toBeVisible();
  // Фото из AD.
  await expect(page.locator("header img")).toHaveAttribute("src", "/api/profile/photo");

  await page.getByLabel("Фамилия Имя Отчество").check();
  await expect(page.getByTestId("address-preview")).toContainText("Сидорова Елена Николаевна");
  await page.getByLabel("Имя Отчество", { exact: true }).check();
  await expect(page.getByTestId("address-preview")).toContainText("Елена Николаевна");

  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/profile");
  await expect(page).toHaveURL(/\/login$/);
});

test("обычный пользователь не видит админку и получает 403", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.getByTestId("user-menu").click();
  await expect(page.getByRole("menuitem", { name: "Админка" })).toHaveCount(0);
  await page.goto("/admin/users");
  await expect(page.getByText("403")).toBeVisible();
});
