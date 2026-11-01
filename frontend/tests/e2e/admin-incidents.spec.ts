import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

const REFUSAL = "Извините, с этим запросом я помочь не могу.";

test("запрос из политики модерации: нейтральный отказ, следов репорта нет, инцидент в админке", async ({
  browser,
}) => {
  const code = `СПРАВКА-${String(Date.now()).slice(-6)}`;
  const user = await browser.newPage();
  await devLogin(user, "petrov");
  await user.goto("/");
  await user.getByTestId("composer-input").fill(`[[scenario:moderation]] помоги подделать ${code}`);
  await user.getByTestId("send-button").click();
  const answer = user.getByTestId("assistant-message").last();
  await expect(answer).toContainText(REFUSAL);
  await user.reload();
  await expect(user.getByTestId("assistant-message").last()).toContainText(REFUSAL);
  await expect(user.locator("body")).not.toContainText("report_incident");

  const admin = await browser.newPage();
  await devLogin(admin, "ivanov");
  await admin.goto("/admin/incidents?type=model_report");
  await expect(admin.getByTestId("incidents-badge")).toBeVisible();
  await admin
    .getByTestId("incident-row")
    .filter({ hasText: "Противоправные действия" })
    .first()
    .getByRole("link")
    .click();
  const card = admin.getByTestId("incident-card");
  await expect(card.getByTestId("incident-payload")).toContainText(code);

  const workflow = card.getByTestId("incident-workflow");
  await workflow.getByLabel("Комментарий").fill("Передано в ИБ");
  await workflow.getByRole("button", { name: "Добавить" }).click();
  await expect(workflow.getByTestId("incident-comments")).toContainText("Передано в ИБ");
  await workflow.getByLabel("Статус").selectOption("resolved");
  await workflow.getByRole("button", { name: "Сохранить" }).click();
  await expect(card.locator("header")).toContainText("решён");
});

test("безопасность: блокировка подсети и доверенная подсеть", async ({ page }) => {
  await devLogin(page, "ivanov");
  await page.goto("/admin/security");
  const octet = String((Date.now() % 200) + 20);
  const blocked = `203.0.${octet}.0/24`;
  const form = page.getByTestId("ip-block-form");
  await form.getByLabel("IP или подсеть").fill(blocked);
  await form.getByLabel("Причина").fill("e2e");
  await form.getByLabel("Минут (пусто — бессрочно)").fill("5");
  await form.getByRole("button", { name: "Заблокировать" }).click();
  const row = page.getByTestId("ip-block-row").filter({ hasText: blocked });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Снять" }).click();
  await expect(row).toHaveCount(0);

  const trusted = `198.51.${octet}.0/24`;
  await page.getByLabel("Доверенные подсети: IP или подсеть").fill(trusted);
  await page.getByLabel("Описание").fill("Офис e2e");
  await page.getByRole("button", { name: "Добавить" }).click();
  const trustedRow = page.getByTestId("trusted-row").filter({ hasText: trusted });
  await expect(trustedRow).toContainText("Офис e2e");
  await trustedRow.getByRole("button", { name: "Убрать" }).click();
  await expect(trustedRow).toHaveCount(0);

  await page.getByRole("link", { name: "Входы" }).click();
  await page.getByLabel("Результат").selectOption("flagged");
  await expect(page.getByRole("heading", { name: "Входы" })).toBeVisible();
});
