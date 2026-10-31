import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { useSelectedScenario } from "@/features/scenarios/api";

import { json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const CONTRACT = {
  id: "s1",
  code: "contract_review",
  name: "Анализ договоров",
  description: "Риски, сроки, обязательства",
  icon: "file-signature",
  starter_prompts: ["Найди риски для нас в этом договоре"],
  requires_attachment: true,
  attachment_hint: "Приложите договор",
  thinking_available: true,
  thinking_default: true,
};
const SUPPORT = {
  ...CONTRACT,
  id: "s2",
  code: "it_support",
  name: "ИТ-поддержка",
  icon: "life-buoy",
  starter_prompts: ["Не подключается VPN — что проверить?"],
  requires_attachment: false,
  attachment_hint: null,
  thinking_default: false,
};

const ROUTES = {
  "GET /api/auth/me": () => json(ME),
  "GET /ready": () => json({ status: "ready", checks: {} }),
  "GET /api/models/chat": () => json({ thinking_available: false, thinking_default: false }),
  "GET /api/folders": () => json([]),
  "GET /api/chats": () => json({ items: [], next_cursor: null }),
  "GET /api/scenarios": () => json([CONTRACT, SUPPORT]),
  "GET /api/files/limits": () => json({ max_file_mb: 50, max_files_per_message: 10, accept: [] }),
  "GET /api/auth/csrf": () => json({ csrf_token: "t" }),
};

afterEach(() => {
  useSelectedScenario.setState({ id: null });
});

describe("Сценарии на стартовом экране", () => {
  it("карточка включает сценарий: примеры, индикатор, «Размышлять», требование вложения", async () => {
    mockFetch(ROUTES);
    renderApp("/");
    const cards = await screen.findAllByTestId("scenario-card");
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringContaining("Анализ договоров"),
      expect.stringContaining("ИТ-поддержка"),
    ]);
    // Без сценария «Размышлять» скрыт (модель чата его не поддерживает).
    expect(screen.queryByTestId("thinking-toggle")).toBeNull();

    await userEvent.click(cards[0] as HTMLElement);
    expect(await screen.findByTestId("scenario-badge")).toHaveTextContent("Анализ договоров");
    expect(screen.getByTestId("examples")).toHaveTextContent("Найди риски для нас в этом договоре");
    expect(screen.getByTestId("thinking-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("attachment-required")).toHaveTextContent("Приложите договор");
    await userEvent.type(screen.getByTestId("composer-input"), "Проверь договор");
    expect(screen.getByTestId("send-button")).toBeDisabled();

    // Сброс сценария кнопкой на индикаторе.
    await userEvent.click(screen.getByRole("button", { name: "Сбросить сценарий" }));
    expect(screen.queryByTestId("scenario-badge")).toBeNull();
    expect(screen.getByTestId("send-button")).toBeEnabled();
  });

  it("чат создаётся с выбранным сценарием", async () => {
    const calls = mockFetch({
      ...ROUTES,
      "POST /api/chats": () => json({ id: "c9", messages: [] }, 201),
      "POST /api/chats/c9/messages": () => json({ error: { code: "x", message: "стоп" } }, 400),
    });
    renderApp("/");
    const cards = await screen.findAllByTestId("scenario-card");
    await userEvent.click(cards[1] as HTMLElement);
    await userEvent.type(screen.getByTestId("composer-input"), "Не работает VPN{Enter}");
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/api/chats"))).toBe(true);
    });
    const create = calls.find((c) => c.method === "POST" && c.url.endsWith("/api/chats"));
    expect(await create?.json()).toMatchObject({ scenario_id: "s2", thinking_enabled: false });
  });
});
