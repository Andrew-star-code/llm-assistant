import { expect, test, type Page } from "@playwright/test";

import { devLogin } from "./helpers";

async function ask(page: Page, text: string): Promise<void> {
  await page.getByTestId("composer-input").fill(text);
  await page.getByTestId("composer-input").press("Enter");
}

const lastAnswer = (page: Page) => page.getByTestId("assistant-message").last();

test("сообщение → стрим → перезагрузка посреди ответа → ответ дописывается полностью", async ({
  page,
}) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "[[scenario:slow]] длинный ответ для перезагрузки");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]+$/);
  await expect(lastAnswer(page)).toContainText("Слово3");
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "streaming");

  await page.reload();
  await expect(lastAnswer(page)).toContainText("Слово40.", { timeout: 20_000 });
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");
  await expect(lastAnswer(page)).toContainText("Слово1 Слово2 Слово3");
});

test("модель обращается по имени и отчеству; заголовок чата генерируется", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "Подскажи порядок оформления командировки");
  await expect(lastAnswer(page)).toContainText("Сергей Алексеевич, это ответ fake-llm");
  await expect(page.getByTestId("chat-title")).toHaveText(
    "Подскажи порядок оформления командировки",
  );
  await expect(page.getByTestId("chat-history")).toContainText(
    "Подскажи порядок оформления командировки",
  );
});

test("«Стоп» сохраняет частичный ответ со статусом stopped", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "[[scenario:slow]] остановите меня");
  await expect(lastAnswer(page)).toContainText("Слово3");
  await page.getByTestId("stop-button").click();
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "stopped");
  await expect(page.getByText("Ответ остановлен")).toBeVisible();
  await page.reload();
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "stopped");
  await expect(lastAnswer(page)).not.toContainText("Слово40.");
});

test("перегенерация создаёт вторую версию, переключатель «‹ 1/2 ›» работает", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "Вопрос для перегенерации");
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");
  await page.getByRole("button", { name: "Перегенерировать" }).click();
  await expect(page.getByTestId("version-label")).toHaveText("2/2");
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");
  await page.getByRole("button", { name: "Предыдущая версия" }).click();
  await expect(page.getByTestId("version-label")).toHaveText("1/2");
  await page.reload();
  await expect(page.getByTestId("version-label")).toHaveText("1/2");
});

test("формулы во всех делимитерах и блоки кода с «Копировать», в том числе во время стрима", async ({
  page,
}) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "[[scenario:markdown]] покажи формулы");
  const answer = lastAnswer(page);
  await expect(answer).toHaveAttribute("data-status", "completed");
  await expect(answer.locator(".katex")).toHaveCount(4);
  await expect(answer.locator(".katex-display")).toHaveCount(2);
  await expect(answer).not.toContainText("\\(");
  const code = answer.getByTestId("code-block");
  await expect(code).toContainText("python");
  await expect(code.getByRole("button", { name: "Копировать" })).toBeVisible();
  await expect(answer.locator("table")).toBeVisible();

  // Во время стрима: незакрытые блоки не ломают вёрстку, формулы уже рендерятся.
  await ask(page, "[[scenario:markdown_slow]] ещё раз медленно");
  const live = lastAnswer(page);
  await expect(live.locator(".katex").first()).toBeVisible();
  await expect(live).toHaveAttribute("data-status", "streaming");
  await expect(live).toHaveAttribute("data-status", "completed", { timeout: 20_000 });
  await expect(live.locator(".katex")).toHaveCount(4);
  await expect(live.getByTestId("code-block")).toContainText("Привет");
});

test("удалённый чат пропадает у пользователя; поиск находит чат по слову из сообщения", async ({
  page,
}) => {
  const word = `Зебра${Date.now()}`;
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, `Расскажи про ${word} и отпуска`);
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");
  const chatUrl = page.url();

  await page.goto("/");
  await expect(page.getByTestId("greeting")).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByTestId("search-input").fill(word);
  await expect(page.getByTestId("search-hit")).toHaveCount(1);
  await expect(page.getByTestId("search-hit").locator("mark").first()).toBeVisible();
  await page.getByTestId("search-hit").click();
  await expect(page).toHaveURL(new RegExp(`${chatUrl.split("/").pop() ?? ""}\\?m=`));

  const item = page.getByTestId("chat-item").filter({ hasText: word });
  await item.hover();
  await item.getByRole("button", { name: "Действия с чатом" }).click();
  await item.getByRole("menuitem", { name: "Удалить" }).click();
  await item.getByRole("menuitem", { name: "Точно удалить?" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("greeting")).toBeVisible();
  await expect(page.getByTestId("chat-history")).not.toContainText(word);

  await page.keyboard.press("Control+k");
  await page.getByTestId("search-input").fill(word);
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
});

test("папки, закрепление и переименование в истории", async ({ page }) => {
  const title = `Чат для папки ${Date.now()}`;
  await devLogin(page, "kim");
  await page.goto("/");
  await ask(page, title);
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");

  const item = page.getByTestId("chat-item").filter({ hasText: title }).first();
  await item.hover();
  await item.getByRole("button", { name: "Действия с чатом" }).click();
  await item.getByRole("menuitem", { name: "Закрепить" }).click();
  await expect(page.getByTestId("chat-history")).toContainText("Закреплённые");

  await page.getByRole("button", { name: "Новая папка" }).click();
  const folderName = `Проекты ${Date.now()}`;
  await page.getByLabel("Название папки").fill(folderName);
  await page.getByLabel("Название папки").press("Enter");
  const folder = page.getByTestId("folder").filter({ hasText: folderName });
  await expect(folder).toBeVisible();
  await item.dragTo(folder);
  await folder.getByRole("button", { name: folderName }).click();
  await expect(folder).toContainText(title);

  // Переименование.
  const inFolder = folder.getByTestId("chat-item").filter({ hasText: title });
  await inFolder.hover();
  await inFolder.getByRole("button", { name: "Действия с чатом" }).click();
  await inFolder.getByRole("menuitem", { name: "Переименовать" }).click();
  await page.getByRole("textbox", { name: "Переименовать" }).fill(`${title} — итог`);
  await page.getByRole("textbox", { name: "Переименовать" }).press("Enter");
  await expect(page.getByTestId("chat-title")).toHaveText(`${title} — итог`);
});
