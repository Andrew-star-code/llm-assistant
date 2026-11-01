import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

describe("SPA", () => {
  it("без сессии уводит на страницу входа", async () => {
    mockFetch({
      "GET /api/auth/me": () => json({ error: { code: "unauthenticated" } }, 401),
      "GET /api/auth/providers": () => json({ providers: ["ldap"], dev_users: [] }),
    });
    const router = renderApp("/profile");
    expect(await screen.findByRole("button", { name: "Войти" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
  });

  it("после входа показывает каркас и приветствие по имени и отчеству", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(ME),
      "GET /ready": () => json({ status: "ready", checks: {} }),
    });
    renderApp("/");
    expect(await screen.findByTestId("greeting")).toHaveTextContent(/, Сергей Алексеевич!$/);
    expect(screen.getByRole("complementary", { name: "Боковая панель" })).toBeInTheDocument();
    expect(await screen.findByText("API готов")).toBeInTheDocument();
  });

  it("показывает уведомление при первом входе", async () => {
    mockFetch({
      "GET /api/auth/me": () =>
        json({ ...ME, notice: { required: true, text: "Переписка сохраняется." } }),
      "GET /ready": () => json({ status: "ready", checks: {} }),
    });
    renderApp("/");
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Переписка сохраняется.");
  });

  it("показывает 404 для неизвестного адреса", async () => {
    mockFetch({});
    renderApp("/nope");
    await waitFor(() => {
      expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
    });
  });
});
