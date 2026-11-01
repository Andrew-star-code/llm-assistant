import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

function stand(permissions: string[]) {
  mockFetch({
    "GET /api/auth/me": () => json({ ...ADMIN_ME, permissions }),
    "GET /api/admin/kb": () => json([]),
    "GET /api/admin/roles": () => json([]),
    "GET /api/admin/kb/search-settings": () =>
      json({
        score_threshold: 0.005,
        default_threshold: 0.005,
        overridden: false,
        updated_at: null,
      }),
  });
}

describe("Админка «Базы знаний»: создание базы", () => {
  it("kb_manager без назначенных баз не видит форму: создавать базы ему нельзя", async () => {
    stand(["admin.access", "admin.kb.manage_roles"]);
    renderApp("/admin/kb");
    expect(await screen.findByRole("heading", { name: "Базы знаний" })).toBeInTheDocument();
    // Форма зависит от профиля: ждём, пока меню покажет раздел, доступный только с профилем.
    expect(await screen.findByRole("link", { name: "Базы знаний" })).toBeInTheDocument();
    expect(screen.queryByText("Новая база знаний")).not.toBeInTheDocument();
  });

  it("с правом admin.kb.manage форма есть", async () => {
    stand(["admin.access", "admin.kb.manage"]);
    renderApp("/admin/kb");
    expect(await screen.findByText("Новая база знаний")).toBeInTheDocument();
  });
});
