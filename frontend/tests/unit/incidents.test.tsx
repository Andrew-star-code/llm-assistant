import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const ADMIN = {
  ...ADMIN_ME,
  permissions: ["admin.access", "admin.incidents.view", "admin.incidents.manage"],
};
const INCIDENT = {
  id: "i1",
  type: "system_error",
  severity: "high",
  status: "new",
  title: "RuntimeError: Сломалось (app/modules/users/router.py:20 in get_profile)",
  occurrences: 2,
  first_seen: "2026-11-01T10:00:00Z",
  last_seen: "2026-11-01T10:05:00Z",
  user: { id: "u1", login: "petrov", full_name: "Петров Сергей Алексеевич" },
  assignee: null,
  chat_id: null,
  message_id: null,
  resolution: null,
  payload: {
    method: "GET",
    path: "/api/profile",
    request_id: "abc123",
    stack: "Traceback (most recent call last):\n  RuntimeError: Сломалось",
    logs: ['{"event": "boom.prepare"}'],
    recent_logs: [],
    environment: { pid: 1 },
  },
  comments: [],
};

describe("Инциденты", () => {
  it("счётчик новых в меню и карточка со стеком, логами и сменой статуса", async () => {
    const patches: unknown[] = [];
    let current: Record<string, unknown> = INCIDENT; // сервер помнит изменения, как настоящий
    mockFetch({
      "GET /api/auth/me": () => json(ADMIN),
      "GET /api/admin/incidents/summary": () => json({ new: 3, new_high: 1, open: 4 }),
      "GET /api/admin/incidents/assignees": () =>
        json([{ id: ADMIN.id, login: "ivanov", full_name: "Иванов Иван Петрович" }]),
      "GET /api/admin/incidents/i1": () => json(current),
      "PATCH /api/admin/incidents/i1": async (request) => {
        const body = (await request.json()) as Record<string, unknown>;
        patches.push(body);
        current = {
          ...INCIDENT,
          status: body.status,
          assignee: { id: ADMIN.id, login: "ivanov", full_name: "Иванов Иван Петрович" },
        };
        return json(current);
      },
    });
    renderApp("/admin/incidents/i1");
    const badge = await screen.findByTestId("incidents-badge");
    expect(badge).toHaveTextContent("3");
    expect(badge.className).toContain("bg-red-600");

    const payload = await screen.findByTestId("incident-payload");
    expect(payload).toHaveTextContent("GET /api/profile");
    expect(payload).toHaveTextContent("Traceback");
    expect(payload).toHaveTextContent("boom.prepare");

    const workflow = screen.getByTestId("incident-workflow");
    await userEvent.selectOptions(within(workflow).getByLabelText("Статус"), "in_progress");
    await userEvent.click(within(workflow).getByRole("button", { name: "Взять себе" }));
    await userEvent.click(within(workflow).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("в работе", { selector: "span" })).toBeInTheDocument();
    expect(patches).toEqual([{ status: "in_progress", assigned_to: ADMIN.id, resolution: null }]);
    expect(await screen.findByRole("status")).toHaveTextContent("Сохранено");
  });

  it("комментарий не стирает несохранённые статус и решение", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(ADMIN),
      "GET /api/admin/incidents/summary": () => json({ new: 1, new_high: 1, open: 1 }),
      "GET /api/admin/incidents/assignees": () => json([]),
      "GET /api/admin/incidents/i1": () => json(INCIDENT),
      "POST /api/admin/incidents/i1/comments": () =>
        json({
          ...INCIDENT,
          comments: [
            {
              id: "c1",
              text: "Передано в ИБ",
              author: { id: ADMIN.id, login: "ivanov", full_name: "Иванов Иван Петрович" },
              created_at: "2026-11-01T10:06:00Z",
            },
          ],
        }),
    });
    renderApp("/admin/incidents/i1");
    const workflow = await screen.findByTestId("incident-workflow");
    await userEvent.selectOptions(within(workflow).getByLabelText("Статус"), "resolved");
    await userEvent.type(within(workflow).getByLabelText("Решение"), "Черновик решения");
    await userEvent.type(within(workflow).getByLabelText("Комментарий"), "Передано в ИБ");
    await userEvent.click(within(workflow).getByRole("button", { name: "Добавить" }));
    expect(await within(workflow).findByText("Передано в ИБ", { selector: "div" })).toBeVisible();
    expect(within(workflow).getByLabelText("Статус")).toHaveValue("resolved");
    expect(within(workflow).getByLabelText("Решение")).toHaveValue("Черновик решения");
  });

  it("раздел без права по прямой ссылке — понятный отказ, а не пустая страница", async () => {
    mockFetch({
      "GET /api/auth/me": () =>
        json({ ...ADMIN_ME, permissions: ["admin.access", "admin.kb.manage_roles"] }),
    });
    renderApp("/admin/incidents");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Недостаточно прав для этого раздела.",
    );
    expect(screen.queryByRole("heading", { name: "Инциденты" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Базы знаний" })).toBeInTheDocument();
  });
});
