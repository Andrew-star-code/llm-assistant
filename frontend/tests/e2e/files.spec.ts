import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { devLogin } from "./helpers";

// Фикстуры сгенерированы backend/tests/samples.py: DOCX на 30 страниц с кодовым словом на 25-й
// и DOCX с подозрительно высокой степенью сжатия (zip-бомба).
const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");
const NEEDLE = "Кодовое слово проекта: ЛАЗУРЬ-7";

async function ask(page: Page, text: string): Promise<void> {
  await page.getByTestId("composer-input").fill(text);
  await page.getByTestId("send-button").click();
}

const lastAnswer = (page: Page) => page.getByTestId("assistant-message").last();
const chips = (page: Page) => page.getByTestId("attachment-chip");

test("DOCX через скрепку → «читаю…» → «готово» → ответ по содержимому", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "report.docx"));
  await expect(chips(page)).toHaveCount(1);
  await expect(chips(page).first()).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(chips(page).first()).toContainText("готово");

  await ask(page, "[[scenario:find]] «Кодовое слово»");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]+$/);
  await expect(lastAnswer(page)).toContainText(`Нашёл в документе: ${NEEDLE}`);
  await expect(page.getByTestId("message-file-chip")).toContainText("report.docx");
  await expect(chips(page)).toHaveCount(0);

  // Дочитывание инструментом: строка статуса видна в ответе и после перезагрузки.
  await ask(page, "[[scenario:tool:read_document]] стр. 25 «Кодовое слово»");
  await expect(lastAnswer(page)).toContainText(NEEDLE);
  await page.reload();
  await expect(page.getByTestId("tool-step").last()).toContainText("Читаю report.docx");
  await expect(page.getByTestId("tool-step").last()).toHaveAttribute("data-status", "ok");
});

test("«Сделай таблицу в Excel» и «Оформи в Word» → карточки файлов, скачивание, просмотр", async ({
  page,
}) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await ask(page, "[[scenario:tool:create_spreadsheet]] Сделай таблицу в Excel");
  const xlsx = page.getByTestId("file-card").last();
  await expect(xlsx).toContainText("Продажи по кварталам.xlsx", { timeout: 30_000 });
  await expect(page.getByTestId("tool-step").last()).toContainText(
    "Создаю таблицу Продажи по кварталам.xlsx",
  );
  const download = page.waitForEvent("download");
  await xlsx.getByRole("link", { name: "Скачать" }).click();
  expect((await download).suggestedFilename()).toBe("Продажи по кварталам.xlsx");

  // PDF-превью Office-файла готовит воркер с LibreOffice; без него кнопки «Просмотр» нет.
  // На стенде с настоящим воркером (E2E_REAL_WORKER=1, `make dev-up`) превью обязательно.
  const preview = xlsx.getByRole("button", { name: "Просмотр" });
  if (process.env.E2E_REAL_WORKER === "1") {
    await expect(preview).toBeVisible();
  }
  if ((await preview.count()) > 0) {
    await preview.click();
    await expect(page.getByTestId("pdf-viewer").locator("canvas").first()).toBeVisible({
      timeout: 30_000,
    });
    await page.keyboard.press("Escape");
  }

  await ask(page, "[[scenario:tool:create_document]] Оформи в Word");
  await expect(page.getByTestId("file-card").last()).toContainText("Формулы.docx", {
    timeout: 30_000,
  });

  await ask(page, "[[scenario:tool:create_csv]] А теперь CSV");
  const csv = page.getByTestId("file-card").last();
  await expect(csv).toContainText("Продажи по кварталам.csv", { timeout: 30_000 });
  await csv.getByRole("button", { name: "Просмотр" }).click();
  const dialog = page.getByTestId("preview-dialog");
  await expect(dialog.getByTestId("csv-preview")).toContainText("Выручка");
  await expect(dialog.getByTestId("csv-preview")).toContainText("I кв.");
  await dialog.getByRole("button", { name: "Закрыть" }).click();
  await expect(dialog).toBeHidden();
});

test("неподдерживаемый, слишком большой файл и zip-бомба → понятные ошибки, чат работает", async ({
  page,
}) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  // Больше 50 МБ Playwright не передаёт буфером — файлы пишем во временный каталог теста.
  const dir = test.info().outputPath();
  mkdirSync(dir, { recursive: true });
  const files = {
    "program.exe": Buffer.from("MZ"),
    "huge.txt": Buffer.alloc(51 * 1024 * 1024, 0x61),
    "bomb.docx": readFileSync(path.join(FIXTURES, "bomb.docx")),
    "fake.pdf": Buffer.from("это не PDF"),
  };
  for (const [name, data] of Object.entries(files)) writeFileSync(path.join(dir, name), data);
  await page
    .getByTestId("file-input")
    .setInputFiles(Object.keys(files).map((name) => path.join(dir, name)));
  await expect(chips(page)).toHaveCount(4);
  await expect(chips(page).nth(0)).toContainText("ошибка: формат не поддерживается");
  await expect(chips(page).nth(1)).toContainText("ошибка: файл больше 50 МБ");
  await expect(chips(page).nth(2)).toContainText("ошибка: Файл отклонён", { timeout: 20_000 });
  await expect(chips(page).nth(3)).toContainText("не соответствует его расширению", {
    timeout: 20_000,
  });

  // Удаление чипа крестиком и обычная отправка — сервис продолжает работать.
  await chips(page).nth(0).getByRole("button").click();
  await expect(chips(page)).toHaveCount(3);
  await ask(page, "Привет после ошибок");
  await expect(lastAnswer(page)).toHaveAttribute("data-status", "completed");
  await expect(lastAnswer(page)).toContainText("Привет после ошибок");
});

test("файл можно перетащить в поле ввода", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  // Строкой: код выполняется в браузере, а у e2e-тестов нет DOM-типов.
  const transfer = await page.evaluateHandle(`(() => {
    const data = new DataTransfer();
    data.items.add(new File(["# Заметка\\n\\nТекст"], "заметка.md", { type: "text/markdown" }));
    return data;
  })()`);
  const composer = page.getByTestId("composer");
  await composer.dispatchEvent("dragover", { dataTransfer: transfer });
  await expect(composer).toContainText("Отпустите, чтобы приложить файлы");
  await composer.dispatchEvent("drop", { dataTransfer: transfer });
  await expect(chips(page).first()).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(chips(page).first()).toContainText("заметка.md");
});

test("PDF из сообщения открывается в просмотрщике pdf.js", async ({ page }) => {
  await devLogin(page, "petrov");
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "memo.pdf"));
  await expect(chips(page).first()).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await ask(page, "[[scenario:find]] «Memo page two»");
  await expect(lastAnswer(page)).toContainText("Нашёл в документе: Memo page two");

  await page.getByTestId("message-file-chip").click();
  const viewer = page.getByTestId("preview-dialog").getByTestId("pdf-viewer");
  // Две страницы — два canvas: воркер pdf.js загрузился локально и отрисовал документ.
  await expect(viewer.locator("canvas")).toHaveCount(2, { timeout: 30_000 });
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("preview-dialog")).toBeHidden();
});
