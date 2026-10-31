import { expect, test, type Page } from "@playwright/test";

import { devLogin } from "./helpers";

const lastAnswer = (page: Page) => page.getByTestId("assistant-message").last();

async function ask(page: Page, text: string): Promise<void> {
  await page.getByTestId("composer-input").fill(text);
  await page.getByTestId("send-button").click();
}

test("сценарий виден только своим ролям", async ({ browser }) => {
  // sidorova — юрист (роль legal): видит «Анализ договоров»; petrov (бухгалтерия) — нет.
  const lawyer = await browser.newPage();
  await devLogin(lawyer, "sidorova");
  await lawyer.goto("/");
  const lawyerCards = lawyer.getByTestId("scenario-card");
  await expect(lawyerCards.filter({ hasText: "Анализ договоров" })).toHaveCount(1);
  await expect(lawyerCards.filter({ hasText: "ИТ-поддержка" })).toHaveCount(1);

  const accountant = await browser.newPage();
  await devLogin(accountant, "petrov");
  await accountant.goto("/");
  await expect(
    accountant.getByTestId("scenario-card").filter({ hasText: "ИТ-поддержка" }),
  ).toHaveCount(1);
  await expect(
    accountant.getByTestId("scenario-card").filter({ hasText: "Анализ договоров" }),
  ).toHaveCount(0);

  // «Анализ договоров» требует вложение: без файла отправить нельзя.
  await lawyerCards.filter({ hasText: "Анализ договоров" }).click();
  await expect(lawyer.getByTestId("attachment-required")).toContainText("Приложите договор");
  await lawyer.getByTestId("composer-input").fill("Найди риски");
  await expect(lawyer.getByTestId("send-button")).toBeDisabled();
});

test("в чате сценария применяется его промпт; сценарий виден в шапке и сбрасывается", async ({
  page,
}) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await page.getByTestId("scenario-card").filter({ hasText: "ИТ-поддержка" }).click();
  await expect(page.getByTestId("examples")).toContainText("Не подключается VPN");
  await ask(page, "[[scenario:find]] «первая линия ИТ-поддержки»");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]+$/);
  await expect(lastAnswer(page)).toContainText(
    "Нашёл в документе: Сценарий «ИТ-поддержка». Ты — первая линия ИТ-поддержки",
  );
  await expect(page.locator("header").getByTestId("scenario-badge")).toContainText("ИТ-поддержка");

  // Сброс: чат продолжается без сценария — промпта ИТ-поддержки больше нет.
  await page.getByRole("button", { name: "Сбросить сценарий" }).click();
  await expect(page.locator("header").getByTestId("scenario-badge")).toHaveCount(0);
  await ask(page, "[[scenario:find]] «первая линия ИТ-поддержки»");
  await expect(lastAnswer(page)).toContainText("В документах нет");
});

test("редактор: новый сценарий, тестовый чат, правка действует без перезапуска", async ({
  page,
}) => {
  await devLogin(page, "ivanov");
  await page.goto("/admin/scenarios");
  await page.getByRole("link", { name: "Новый сценарий" }).click();
  const code = `e2e-${String(Date.now())}`;
  const form = page.getByTestId("scenario-form");
  await form.getByLabel("Название").fill(`Тестовый ${code}`);
  await form.getByLabel("Код (латиница)").fill(code);
  await page.getByTestId("scenario-prompt").fill("Версия один: {{ user.address }}.");
  // Выключенный сценарий не появляется у пользователей, а тестовый чат с ним работает.
  await form.getByLabel("Активен").uncheck();
  await page.getByTestId("scenario-save").click();
  await expect(page).toHaveURL(/\/admin\/scenarios\/[0-9a-f-]+$/);
  await expect(page.getByTestId("scenario-saved")).toBeVisible();

  const chat = page.getByTestId("test-chat");
  await chat.getByRole("button", { name: "Начать" }).click();
  await chat.getByTestId("composer-input").fill("[[scenario:find]] «Версия»");
  await chat.getByTestId("send-button").click();
  await expect(chat.getByTestId("assistant-message").last()).toContainText(
    "Нашёл в документе: Версия один: Иван Петрович.",
  );

  await page.getByTestId("scenario-prompt").fill("Версия два.");
  await page.getByTestId("scenario-save").click();
  await expect(page.getByTestId("scenario-saved")).toBeVisible();
  await chat.getByTestId("composer-input").fill("[[scenario:find]] «Версия»");
  await chat.getByTestId("send-button").click();
  await expect(chat.getByTestId("assistant-message").last()).toContainText(
    "Нашёл в документе: Версия два.",
  );

  // Ошибка в шаблоне — понятное сообщение, сценарий не сохраняется.
  await page.getByTestId("scenario-prompt").fill("{{ user.");
  await page.getByTestId("scenario-save").click();
  await expect(page.getByTestId("scenario-error")).toContainText("Ошибка в шаблоне промпта");
});
