import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const MANAGER = {
  ...ADMIN_ME,
  permissions: ["admin.access", "admin.users.view", "admin.roles.manage"],
};
const ROLE = {
  id: "r1",
  code: "legal",
  name: "Юристы",
  kind: "custom",
  description: null,
  users: 0,
  editable: true,
  knowledge_bases: [],
  scenarios: ["Анализ договоров"],
};

describe("Админка «Роли»", () => {
  it("массово добавляет сотрудников списком и оставляет в поле ненайденных", async () => {
    const sent: unknown[] = [];
    mockFetch({
      "GET /api/auth/me": () => json(MANAGER),
      "GET /api/admin/roles/r1": () => json(ROLE),
      "GET /api/admin/roles/r1/members": () => json({ items: [], next_cursor: null }),
      "POST /api/admin/roles/r1/members": async (request) => {
        sent.push(await request.json());
        return json({
          added: [{ id: "u1", login: "petrov", full_name: "Петров", department: null }],
          already: [],
          created: ["sidorova"],
          not_found: ["nobody"],
        });
      },
    });
    renderApp("/admin/roles/r1");
    expect(await screen.findByText("Открывает: Анализ договоров")).toBeInTheDocument();
    await userEvent.type(screen.getByTestId("bulk-input"), "petrov, sidorova@corp.local;nobody");
    await userEvent.click(screen.getByRole("button", { name: "Добавить (3)" }));
    expect(await screen.findByTestId("bulk-result")).toHaveTextContent(
      "Добавлено: 1 · уже были: 0 · заведено из AD: 1",
    );
    expect(screen.getByText(/Не найдены в AD: nobody/)).toBeInTheDocument();
    expect(sent).toEqual([{ identifiers: ["petrov", "sidorova@corp.local", "nobody"] }]);
    expect(screen.getByTestId("bulk-input")).toHaveValue("nobody");
  });
});
