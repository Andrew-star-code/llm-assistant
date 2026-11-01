import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

describe("Админка", () => {
  it("без права admin.access — 403", async () => {
    mockFetch({ "GET /api/auth/me": () => json(ME) });
    renderApp("/admin/users");
    expect(await screen.findByText("403")).toBeInTheDocument();
  });

  it("показывает только разделы, на которые есть права", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(ADMIN_ME),
      "GET /api/admin/users": () =>
        json({
          items: [
            {
              id: "u1",
              login: "petrov",
              full_name: "Петров Сергей Алексеевич",
              title: "Бухгалтер",
              department: "Бухгалтерия",
              is_blocked: true,
              ad_disabled: false,
              last_login_at: null,
            },
          ],
          next_cursor: null,
        }),
    });
    const router = renderApp("/admin");
    expect(
      await screen.findByRole("link", { name: "Петров Сергей Алексеевич" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/admin/users");
    expect(screen.getByText("Заблокирован")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Админка" });
    expect(nav).toHaveTextContent("Журнал аудита");
    expect(nav).not.toHaveTextContent("Входы");
    expect(nav).not.toHaveTextContent("Диагностика AD");
  });
});
