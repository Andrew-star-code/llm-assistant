import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

// regulation.pdf (backend/tests/samples.py::text_pdf): кодовое слово — на 2-й странице.
const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");
const CODE = "ORION-2026-KB";

test("ответ по документу общей базы: [1], карточка, клик открывает нужную страницу PDF", async ({
  browser,
}) => {
  const admin = await browser.newPage();
  await devLogin(admin, "ivanov");
  await admin.goto("/admin/kb");
  const code = `regs-${String(Date.now())}`;
  const form = admin.getByTestId("kb-create-form");
  await form.getByLabel("Код (латиница, например regulations)").fill(code);
  await form.getByLabel("Название").fill(`Регламенты ${code}`);
  await form.getByRole("button", { name: "Создать" }).click();
  await admin.getByRole("link", { name: `Регламенты ${code}` }).click();
  await expect(admin.getByTestId("kb-title")).toHaveText(`Регламенты ${code}`);
  await admin.getByTestId("kb-file-input").setInputFiles(path.join(FIXTURES, "regulation.pdf"));
  const doc = admin.getByTestId("kb-document").first();
  await expect(doc).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(doc).toContainText("regulation");
  await admin.close();

  const page = await browser.newPage();
  await devLogin(page, "petrov");
  await page.goto("/");
  await page.getByTestId("composer-input").fill(`[[scenario:find]] «${CODE}»`);
  await page.getByTestId("send-button").click();
  const answer = page.getByTestId("assistant-message").last();
  await expect(answer).toContainText(`Kodovoe slovo ${CODE} zdes`);
  await expect(answer.getByTestId("citation")).toHaveText("1");
  await expect(page.getByTestId("tool-step").first()).toContainText("Ищу в базах знаний");
  const card = page.getByTestId("source-card").first();
  await expect(card).toContainText("regulation");
  await expect(card).toContainText("стр. 2");

  await answer.getByTestId("citation").click();
  const viewer = page.getByTestId("preview-dialog").getByTestId("pdf-viewer");
  await expect(viewer).toHaveAttribute("data-initial-page", "2");
  await expect(viewer.locator('[data-page-number="2"] canvas')).toBeInViewport({ timeout: 30_000 });

  // После перезагрузки — те же карточка и цитата из истории.
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(page.getByTestId("source-card").first()).toContainText("стр. 2");
  await expect(page.getByTestId("citation").first()).toHaveText("1");
});

test("«Моя база знаний»: загрузка, статус, квота, удаление", async ({ page }) => {
  await devLogin(page, "kim");
  await page.goto("/");
  await page.getByTestId("open-personal-kb").click();
  await expect(page.getByRole("heading", { name: "Моя база знаний" })).toBeVisible();
  const name = `заметка-${String(Date.now())}`;
  await page.getByTestId("kb-file-input").setInputFiles({
    name: `${name}.md`,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# Заметка\n\nЛичный план ${name}.`),
  });
  const doc = page.getByTestId("kb-document").filter({ hasText: name });
  await expect(doc).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(page.getByTestId("kb-quota")).toContainText("из 100");

  // Дубль по содержимому — понятная ошибка.
  await page.getByTestId("kb-file-input").setInputFiles({
    name: "копия.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(`# Заметка\n\nЛичный план ${name}.`),
  });
  await expect(page.getByTestId("kb-upload-errors")).toContainText("уже есть в базе");

  await doc.getByRole("button", { name: `Удалить «${name}»` }).click();
  await doc.getByRole("button", { name: "Точно удалить?" }).click();
  await expect(doc).toHaveCount(0);
});

test("админка: разделы «Базы знаний» и «Инциденты»", async ({ page }) => {
  await devLogin(page, "ivanov");
  await page.goto("/admin");
  await page.getByRole("link", { name: "Инциденты" }).click();
  await expect(page.getByRole("heading", { name: "Инциденты" })).toBeVisible();
  await page.getByRole("link", { name: "Базы знаний" }).first().click();
  await expect(page.getByTestId("kb-create-form")).toBeVisible();
});
