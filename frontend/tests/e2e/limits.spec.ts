import { expect, test, type Page } from "@playwright/test";

import { devLogin } from "./helpers";

const EXHAUSTED =
  "Дневной лимит сообщений исчерпан, обновится в 00:00. " +
  "Если нужно больше — обратитесь к администратору.";

/** Удаляет персональные политики Смирновой, оставшиеся от прошлых прогонов, и сбрасывает счётчики. */
async function cleanup(admin: Page): Promise<void> {
  await admin.goto("/admin/limits");
  const rows = admin.getByTestId("limit-policy-row").filter({ hasText: "Смирнова" });
  await expect(admin.getByTestId("limit-default-row").first()).toBeVisible();
  while ((await rows.count()) > 0) {
    const before = await rows.count();
    await rows.first().getByRole("button", { name: "Удалить" }).click();
    await expect(rows).toHaveCount(before - 1);
  }
}

test("лимит: временное повышение до нуля, 429 с понятным сообщением, поле ввода закрыто", async ({
  browser,
}) => {
  const admin = await browser.newPage();
  await devLogin(admin, "ivanov");
  await cleanup(admin);

  // Пользователь открыл чат, пока лимит ещё есть.
  const user = await browser.newPage();
  await devLogin(user, "smirnova");
  await user.goto("/");
  await expect(user.getByTestId("limit-note")).toContainText("сообщений · обновится в 00:00");

  // Админ в карточке пользователя «временно повышает» лимит сообщений до 0 на день.
  await admin.goto("/admin/users?q=smirnova");
  await admin
    .getByRole("link", { name: /Смирнова/ })
    .first()
    .click();
  const block = admin.getByTestId("user-limits");
  const form = block.getByTestId("raise-limit-form");
  await form.getByLabel("Метрика").selectOption("messages");
  await form.getByLabel("Значение").fill("0");
  await form.getByLabel("Дней").fill("1");
  await form.getByRole("button", { name: "Повысить" }).click();
  const messages = block.getByTestId("user-limit-row").filter({ hasText: "Сообщения · в день" });
  await expect(messages).toContainText("персональная");

  // Отправка упирается в лимит: 429 и понятный текст, затем поле ввода закрыто.
  await user.getByTestId("composer-input").fill("Вопрос сверх лимита");
  await user.getByTestId("send-button").click();
  await expect(user.getByRole("alert").filter({ hasText: "Дневной лимит" }).first()).toHaveText(
    EXHAUSTED,
  );
  await expect(user.getByTestId("limit-blocked")).toHaveText(EXHAUSTED);
  await expect(user.getByTestId("composer-input")).toBeDisabled();

  // Профиль: полная картина по метрикам.
  await user.goto("/profile#limits");
  await expect(user.getByTestId("limit-messages")).toContainText("из 0");

  // Админ убирает политику — поле снова открыто.
  await cleanup(admin);
  await user.goto("/");
  await expect(user.getByTestId("composer-input")).toBeEnabled();
  await expect(user.getByTestId("limit-blocked")).toHaveCount(0);
});
