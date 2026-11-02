import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

// Этап 9 (§9.5): «Кадровый бот» ищет в телефонном справочнике через data-gateway (на дев-стенде —
// mock-mssql), а каждый запрос виден в «Источниках данных».
test("Кадровый бот: телефон из справочника, запрос в журнале источников данных", async ({
  browser,
}) => {
  const user = await browser.newPage();
  await devLogin(user, "kim");
  await user.goto("/");
  await user.getByTestId("scenario-card").filter({ hasText: "Кадровый бот" }).click();
  await user.getByTestId("composer-input").fill("Найди телефон Петрова из бухгалтерии");
  await user.getByTestId("send-button").click();
  const answer = user.getByTestId("assistant-message").last();
  await expect(answer).toContainText("+7 (495) 100-20-02", { timeout: 30_000 });
  await expect(user.getByTestId("tool-step").last()).toContainText("Ищу в справочнике: «Петров»");
  await expect(user.getByTestId("tool-step").last()).toHaveAttribute("data-status", "ok");

  const admin = await browser.newPage();
  await devLogin(admin, "ivanov");
  await admin.goto("/admin/data");
  await expect(admin.getByTestId("dataset-row").first()).toContainText("Телефонный справочник");
  const card = admin.getByTestId("function-card").filter({ hasText: "search_employees" });
  await card.getByLabel("query").fill("Сидоров");
  await card.getByRole("button", { name: "Выполнить" }).click();
  await expect(card).toContainText("Сидорова Елена Николаевна");
  const row = admin.getByTestId("query-row").filter({ hasText: "Ким Александр" }).first();
  await expect(row).toContainText("search_employees");
  await expect(row).toContainText("выполнен");
});
