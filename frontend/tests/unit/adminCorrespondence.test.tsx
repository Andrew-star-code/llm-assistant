import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const VIEWER = {
  ...ADMIN_ME,
  permissions: ["admin.access", "admin.chats.view", "admin.chats.export", "admin.dashboard.view"],
};
const USER = {
  id: "u1",
  login: "petrov",
  full_name: "Петров Сергей Алексеевич",
  department: "Бухгалтерия",
};
const OPTIONS = { departments: ["Бухгалтерия"], scenarios: [], models: ["fake-chat"] };

function message(id: string, role: string, content: string, extra: object = {}) {
  return {
    id,
    parent_id: null,
    role,
    content,
    reasoning: null,
    status: "completed",
    thinking: false,
    model: role === "assistant" ? "fake-chat" : null,
    finish_reason: null,
    prompt_tokens: null,
    completion_tokens: null,
    reasoning_tokens: null,
    ttft_ms: null,
    latency_ms: null,
    reasoning_ms: null,
    error: null,
    trace: null,
    created_at: "2026-11-01T10:00:00Z",
    deleted_at: null,
    tool_calls: [],
    sources: [],
    files: [],
    feedback: null,
    ...extra,
  };
}

describe("Админка «Переписка»", () => {
  it("поиск по слову показывает фрагменты с подсветкой и ведёт в чат", async () => {
    const calls = mockFetch({
      "GET /api/auth/me": () => json(VIEWER),
      "GET /api/admin/chats/filters": () => json(OPTIONS),
      "GET /api/admin/chats": () => json({ items: [], next_cursor: null }),
      "GET /api/admin/messages": () =>
        json({
          items: [
            {
              message_id: "m1",
              chat_id: "c1",
              chat_title: "Отчёт",
              user: USER,
              role: "user",
              created_at: "2026-11-01T10:00:00Z",
              model: null,
              scenario: null,
              deleted: true,
              is_test: false,
              disliked: false,
              has_incident: false,
              has_attachments: false,
              fragments: [
                { text: "Подготовь ", match: false },
                { text: "квартальный", match: true },
              ],
            },
          ],
          next_cursor: null,
        }),
    });
    renderApp("/admin/chats");
    const nav = await screen.findByRole("navigation", { name: "Админка" });
    expect(nav).toHaveTextContent("Переписка");
    expect(nav).toHaveTextContent("Дашборд");
    expect(nav).not.toHaveTextContent("Настройки");

    await userEvent.type(screen.getByTestId("admin-chat-search"), "квартального");
    await userEvent.click(screen.getByRole("button", { name: "Поиск" }));
    const hit = await screen.findByTestId("admin-message-hit");
    expect(within(hit).getByText("квартальный").tagName).toBe("MARK");
    expect(within(hit).getByText("удалён")).toBeInTheDocument();
    expect(within(hit).getByRole("link", { name: "Отчёт" })).toHaveAttribute(
      "href",
      "/admin/chats/c1#m-m1",
    );
    const search = calls.find((r) => r.url.includes("/api/admin/messages"));
    expect(new URL(search?.url ?? "").searchParams.get("q")).toBe("квартального");
  });

  it("просмотр чата: ветки, скрытый вызов инструмента, пометка об аудите", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(VIEWER),
      "GET /api/admin/chats/c1": () =>
        json({
          id: "c1",
          title: "Отчёт",
          user: USER,
          scenario: null,
          is_test: false,
          created_at: "2026-11-01T10:00:00Z",
          last_message_at: "2026-11-01T10:01:00Z",
          deleted_at: "2026-11-02T10:00:00Z",
          deleted_by: USER,
          active_leaf_id: "a2",
          messages: [
            message("q1", "user", "Вопрос"),
            message("a1", "assistant", "Первый ответ", { parent_id: "q1" }),
            message("a2", "assistant", "Второй ответ", {
              parent_id: "q1",
              tool_calls: [
                {
                  call_id: "h",
                  tool: "report_incident",
                  visibility: "hidden",
                  status: "ok",
                  iteration: 1,
                  duration_ms: 3,
                  arguments: {},
                  result_preview: null,
                  created_at: "2026-11-01T10:00:00Z",
                },
              ],
            }),
          ],
        }),
    });
    renderApp("/admin/chats/c1");
    expect(await screen.findByText("Просмотр записан в журнал аудита")).toBeInTheDocument();
    const [, first, second] = screen.getAllByTestId("admin-message");
    expect(screen.getAllByTestId("admin-message")).toHaveLength(3);
    if (!first || !second) throw new Error("нет сообщений");
    expect(within(first).getByText("не в активной ветке")).toBeInTheDocument();
    expect(within(second).getByText("версия 2")).toBeInTheDocument();
    expect(within(second).getByText("скрытый")).toBeInTheDocument();
    expect(screen.getByText(/Удалён пользователем/)).toBeInTheDocument();
    // Восстановление и удаление — только с правами: у этого админа их нет.
    expect(screen.queryByRole("button", { name: "Вернуть пользователю" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Удалить навсегда" })).toBeNull();
    expect(screen.getByRole("button", { name: "Выгрузить" })).toBeInTheDocument();
  });
});
