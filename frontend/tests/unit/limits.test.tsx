import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN_ME, json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

/** Ближайшая полночь по часам браузера — так сервер считает «обновится в 00:00». */
function nextMidnight(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).toISOString();
}

function limits(used: number, limit = 200) {
  const reset = nextMidnight();
  const item = (metric: string, u: number, l: number, window: string | null = "day") => ({
    metric,
    window,
    model_role: null,
    thinking: false,
    limit: l,
    used: u,
    remaining: Math.max(0, l - u),
    reset_at: window ? reset : null,
  });
  return {
    items: [
      item("messages", used, limit),
      item("tokens", 300_000, 2_000_000),
      item("concurrent_generations", 0, 2, null),
      item("personal_kb_storage", 12, 500, null),
    ],
    nearest: {
      metric: "messages",
      window: "day",
      limit,
      used,
      remaining: Math.max(0, limit - used),
      reset_at: reset,
    },
    blocked: used >= limit,
  };
}

const HOME = {
  "GET /ready": () => json({ status: "ready", checks: {} }),
  "GET /api/models/chat": () => json({ thinking_available: false, thinking_default: false }),
};

describe("Лимиты", () => {
  it("поле ввода показывает остаток по метрике, ближайшей к исчерпанию", async () => {
    mockFetch({
      ...HOME,
      "GET /api/auth/me": () => json(ME),
      "GET /api/limits": () => json(limits(163)),
    });
    renderApp("/");
    expect(await screen.findByTestId("limit-note")).toHaveTextContent(
      "Осталось 37 из 200 сообщений · обновится в 00:00",
    );
    expect(screen.getByTestId("composer-input")).toBeEnabled();
  });

  it("при исчерпании поле ввода закрыто с пояснением", async () => {
    mockFetch({
      ...HOME,
      "GET /api/auth/me": () => json(ME),
      "GET /api/limits": () => json(limits(200)),
    });
    renderApp("/");
    expect(await screen.findByTestId("limit-blocked")).toHaveTextContent(
      "Дневной лимит сообщений исчерпан, обновится в 00:00. " +
        "Если нужно больше — обратитесь к администратору.",
    );
    expect(screen.getByTestId("composer-input")).toBeDisabled();
  });

  it("ответ 429 превращается в понятное сообщение", async () => {
    mockFetch({
      ...HOME,
      "GET /api/auth/me": () => json(ME),
      "GET /api/limits": () => json(limits(10)),
      "POST /api/chats": () =>
        json({ id: "c1", title: null, folder_id: null, pinned: false, messages: [] }, 201),
      "POST /api/chats/c1/messages": () =>
        json(
          {
            error: {
              code: "limit_exceeded",
              message: "server text",
              details: {
                metric: "tokens",
                window: "week",
                model_role: null,
                thinking: true,
                limit: 10,
                used: 12,
                reset_at: "2026-11-09T00:00:00+03:00",
              },
            },
          },
          429,
        ),
    });
    renderApp("/");
    await userEvent.type(await screen.findByTestId("composer-input"), "Вопрос{Enter}");
    const alert = await screen.findByText(/лимит токенов в режиме размышлений исчерпан/);
    expect(alert).toHaveTextContent(
      /^Недельный лимит токенов в режиме размышлений исчерпан, обновится/,
    );
    expect(alert).toHaveTextContent("Если нужно больше — обратитесь к администратору.");
  });

  it("профиль показывает полосы по всем метрикам", async () => {
    mockFetch({
      "GET /api/auth/me": () => json(ME),
      "GET /api/profile": () =>
        json({
          ...ME,
          company: null,
          office: null,
          email: null,
          phone: null,
          mobile: null,
          manager_name: null,
          address_form: null,
        }),
      "GET /api/limits": () => json(limits(50)),
    });
    renderApp("/profile");
    const section = await screen.findByTestId("profile-limits");
    expect(await within(section).findByTestId("limit-messages")).toHaveTextContent(
      "Сообщения · в день",
    );
    expect(within(section).getByTestId("limit-messages")).toHaveTextContent("50 из 200");
    expect(within(section).getByTestId("limit-tokens")).toHaveTextContent("300 тыс. из 2 млн");
    expect(within(section).getAllByRole("progressbar")).toHaveLength(4);
  });

  it("админка: новая ролевая политика и значения из конфигурации", async () => {
    const posted: unknown[] = [];
    mockFetch({
      "GET /api/auth/me": () =>
        json({ ...ADMIN_ME, permissions: ["admin.access", "admin.limits.manage"] }),
      "GET /api/admin/roles": () =>
        json([
          {
            id: "r1",
            code: "it",
            name: "ИТ",
            kind: "manual",
            description: null,
            users: 3,
            permissions: [],
          },
        ]),
      "GET /api/admin/limits/policies": () =>
        json({
          items: [],
          defaults: [
            { metric: "messages", window: "day", limit: 200, model_role: null, thinking: false },
          ],
          model_roles: ["chat", "coder"],
        }),
      "POST /api/admin/limits/policies": async (request) => {
        posted.push(await request.json());
        return json({}, 201);
      },
    });
    renderApp("/admin/limits");
    expect(await screen.findByTestId("limit-default-row")).toHaveTextContent("Сообщения · в день");
    const form = screen.getByTestId("limit-policy-form");
    await userEvent.selectOptions(within(form).getByLabelText("Роль"), "r1");
    await userEvent.selectOptions(within(form).getByLabelText("Метрика"), "tokens");
    await userEvent.selectOptions(within(form).getByLabelText("Окно"), "week");
    await userEvent.type(within(form).getByLabelText("Значение"), "5000000");
    await userEvent.click(within(form).getByRole("checkbox", { name: "только размышления" }));
    await userEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await screen.findByTestId("limit-policy-form");
    expect(posted).toEqual([
      {
        scope: "role",
        target_id: "r1",
        metric: "tokens",
        window: "week",
        limit: 5_000_000,
        model_role: null,
        thinking: true,
        expires_at: null,
        note: null,
      },
    ]);
  });
});
