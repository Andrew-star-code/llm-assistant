import { expect, type Page } from "@playwright/test";

/** Вход провайдером dev (seed-пользователи из config/app.dev.yaml) и подтверждение уведомления. */
export async function devLogin(page: Page, login: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId(`dev-login-${login}`).click();
  await acceptNotice(page);
}

/** Подтверждает уведомление при первом входе, если оно есть (показывается один раз). */
export async function acceptNotice(page: Page): Promise<void> {
  // Уведомление рендерится вместе с каркасом: когда меню пользователя на месте, всё решено.
  await expect(page.getByTestId("user-menu")).toBeAttached();
  const dialog = page.getByRole("dialog");
  if ((await dialog.count()) > 0) {
    await dialog.getByRole("button", { name: "Понятно" }).click();
    await expect(dialog).toBeHidden();
  }
}
