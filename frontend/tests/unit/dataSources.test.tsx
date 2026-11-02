import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const ADMIN = { ...ADMIN_ME, permissions: ["admin.access", "admin.datasources.view"] };

describe("Источники данных", () => {
  it("каталог, тестовый вызов функции и журнал запросов", async () => {
    const calls: unknown[] = [];
    mockFetch({
      "GET /api/auth/me": () => json(ADMIN),
      "GET /api/admin/data/catalog": () =>
        json({
          configured: true,
          catalog_error: null,
          error: null,
          datasets: [
            {
              name: "phonebook",
              title: "Телефонный справочник",
              description: "Сотрудники",
              view: "dbo.v_phonebook",
              source: "mssql_main",
              roles: [],
              columns: 7,
              rls: [{ column: "department", equals: "{user.department}", unless_roles: ["hr"] }],
            },
          ],
          functions: [
            {
              name: "search_employees",
              description: "Найти сотрудников",
              params: { query: { type: "string" }, department: { required: false } },
              roles: [],
              sql: "SELECT TOP (:limit) full_name FROM dbo.v_phonebook",
            },
          ],
        }),
      "POST /api/admin/data/functions/search_employees/test": async (request) => {
        calls.push(await request.json());
        return json({
          columns: ["full_name", "phone"],
          rows: [["Смирнова Анна Викторовна", "+7 (495) 100-20-01"]],
          row_count: 1,
          truncated: false,
          duration_ms: 12,
          sql: "SELECT TOP (:limit) full_name FROM dbo.v_phonebook",
        });
      },
      "GET /api/admin/data/queries": () =>
        json({
          items: [
            {
              id: "q1",
              ts: "2026-11-02T10:00:00Z",
              user: "Петров Сергей Алексеевич",
              action: "data.query",
              target: "sql",
              sql: "DELETE FROM dbo.v_phonebook",
              status: "rejected",
              rows: null,
              duration_ms: null,
              error: "разрешён только SELECT",
              chat_id: "c1",
            },
          ],
          next_cursor: null,
        }),
    });
    renderApp("/admin/data");
    const row = await screen.findByTestId("dataset-row");
    expect(row).toHaveTextContent("Телефонный справочник");
    expect(row).toHaveTextContent("department = {user.department}");
    expect(row).toHaveTextContent("кроме hr");
    const card = screen.getByTestId("function-card");
    await userEvent.type(within(card).getByLabelText("query"), "Смирнов");
    await userEvent.click(within(card).getByRole("button", { name: "Выполнить" }));
    expect(await within(card).findByText("Смирнова Анна Викторовна")).toBeInTheDocument();
    expect(calls).toEqual([{ params: { query: "Смирнов" } }]);
    const journal = await screen.findByTestId("query-row");
    expect(journal).toHaveTextContent("DELETE FROM dbo.v_phonebook");
    expect(journal).toHaveTextContent("отклонён");
  });

  it("шлюз не настроен — честное сообщение", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(ADMIN),
      "GET /api/admin/data/catalog": () =>
        json({ configured: false, datasets: [], functions: [], catalog_error: null, error: null }),
      "GET /api/admin/data/queries": () => json({ items: [], next_cursor: null }),
    });
    renderApp("/admin/data");
    expect(await screen.findByRole("status")).toHaveTextContent("Шлюз данных не настроен");
  });
});
