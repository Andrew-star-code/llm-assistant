import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("тема переключается и сохраняется после перезагрузки", async ({ page }) => {
  await devLogin(page, "kim");
  await expect(page.getByRole("complementary", { name: "Боковая панель" })).toBeVisible();

  const html = page.locator("html");
  await page.getByTestId("user-menu").click();
  await page.getByTestId("theme-dark").click();
  await expect(html).toHaveClass(/dark/);

  await page.reload();
  await expect(html).toHaveClass(/dark/);

  await page.getByTestId("user-menu").click();
  await page.getByTestId("theme-light").click();
  await page.reload();
  await expect(html).not.toHaveClass(/dark/);
});
