import { expect, test } from "@playwright/test";

test("SPA открывается, тема переключается и сохраняется после перезагрузки", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("complementary", { name: "Боковая панель" })).toBeVisible();

  const html = page.locator("html");
  await page.getByTestId("theme-dark").click();
  await expect(html).toHaveClass(/dark/);

  await page.reload();
  await expect(html).toHaveClass(/dark/);
  await expect(page.getByTestId("theme-dark")).toHaveAttribute("aria-checked", "true");

  await page.getByTestId("theme-light").click();
  await page.reload();
  await expect(html).not.toHaveClass(/dark/);
});

test("админка открывается по ссылке из боковой панели", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Админка" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByText("Разделы админки появятся")).toBeVisible();
});
