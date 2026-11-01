import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const KB_ADMIN = { ...ADMIN_ME, permissions: ["admin.access", "admin.kb.manage"] };

describe("Админка «Базы знаний» → «Параметры поиска»", () => {
  it("меняет порог реранкера и возвращает значение из конфигурации", async () => {
    const fromConfig = {
      score_threshold: 0.005,
      default_threshold: 0.005,
      overridden: false,
      updated_at: null,
    };
    const overridden = {
      score_threshold: 0.03,
      default_threshold: 0.005,
      overridden: true,
      updated_at: "2026-11-01T10:00:00Z",
    };
    const sent: unknown[] = [];
    mockFetch({
      "GET /api/auth/me": () => json(KB_ADMIN),
      "GET /api/admin/kb": () => json([]),
      "GET /api/admin/roles": () => json([]),
      "GET /api/admin/kb/search-settings": () => json(fromConfig),
      "PUT /api/admin/kb/search-settings": async (request) => {
        const body = (await request.json()) as { score_threshold: number | null };
        sent.push(body.score_threshold);
        return json(body.score_threshold === null ? fromConfig : overridden);
      },
    });
    renderApp("/admin/kb");
    const input = await screen.findByLabelText("Порог реранкера (0–1)");
    expect(input).toHaveValue(0.005);
    expect(screen.getByTestId("kb-search-source")).toHaveTextContent("из конфигурации");

    await userEvent.clear(input);
    await userEvent.type(input, "0.03");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByTestId("kb-search-source")).toHaveTextContent("Задан в админке");
    expect(sent).toEqual([0.03]);
    expect(screen.getByRole("status")).toHaveTextContent("действует со следующего поиска");

    await userEvent.click(screen.getByRole("button", { name: /Вернуть из конфигурации/ }));
    await waitFor(() => {
      expect(screen.getByTestId("kb-search-source")).toHaveTextContent("из конфигурации");
    });
    expect(sent).toEqual([0.03, null]);
    expect(screen.getByLabelText("Порог реранкера (0–1)")).toHaveValue(0.005);
  });
});
