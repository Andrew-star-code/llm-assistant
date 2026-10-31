import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

type Listener = (event: Event) => void;

/** Заглушка EventSource: тест сам «присылает» события протокола. */
class FakeEventSource {
  static last: FakeEventSource | null = null;
  readyState = 1;
  listeners = new Map<string, Listener[]>();
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(name: string, listener: Listener) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }
  emit(name: string, data: unknown) {
    const event = new MessageEvent(name, { data: JSON.stringify(data) });
    this.listeners.get(name)?.forEach((l) => {
      l(event);
    });
  }
  close() {
    this.readyState = 2;
  }
}

function message(
  id: string,
  parent: string | null,
  role: "user" | "assistant",
  extra: Record<string, unknown> = {},
) {
  return {
    id,
    parent_id: parent,
    role,
    chat_id: "c1",
    content: `текст ${id}`,
    reasoning: null,
    status: "completed",
    thinking: false,
    model: "fake-chat",
    finish_reason: "stop",
    prompt_tokens: 10,
    completion_tokens: 5,
    reasoning_tokens: null,
    reasoning_ms: null,
    ttft_ms: 100,
    latency_ms: 900,
    error: null,
    created_at: `2026-10-31T10:0${id.length}:00Z`,
    feedback: null,
    ...extra,
  };
}

function chat(messages: unknown[], leaf: string) {
  return {
    id: "c1",
    title: "Отпуск",
    folder_id: null,
    pinned: false,
    last_message_at: "2026-10-31T10:00:00Z",
    created_at: "2026-10-31T10:00:00Z",
    active_leaf_id: leaf,
    thinking_enabled: null,
    messages,
  };
}

const COMMON = {
  "GET /api/auth/me": () => json(ME),
  "GET /ready": () => json({ status: "ready", checks: {} }),
  "GET /api/models/chat": () => json({ thinking_available: true, thinking_default: false }),
  "GET /api/folders": () => json([]),
  "GET /api/chats": () => json({ items: [], next_cursor: null }),
};

describe("Лента чата", () => {
  it("дописывает ответ из SSE и показывает размышления", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    let finished = false;
    const streaming = chat(
      [
        message("u", null, "user"),
        message("aa", "u", "assistant", { status: "streaming", content: "" }),
      ],
      "aa",
    );
    const done = chat(
      [message("u", null, "user"), message("aa", "u", "assistant", { content: "Готовый ответ" })],
      "aa",
    );
    mockFetch({ ...COMMON, "GET /api/chats/c1": () => json(finished ? done : streaming) });
    renderApp("/c/c1");

    await waitFor(() => {
      expect(FakeEventSource.last?.url).toBe("/api/messages/aa/stream");
    });
    const source = FakeEventSource.last as FakeEventSource;
    source.emit("reasoning.delta", { text: "Думаю…" });
    source.emit("content.delta", { text: "Частичный " });
    source.emit("content.delta", { text: "ответ" });
    expect(await screen.findByText("Частичный ответ")).toBeInTheDocument();
    expect(screen.getByTestId("reasoning")).toHaveTextContent("Думаю…");

    finished = true;
    source.emit("message.end", { status: "completed", finish_reason: "stop" });
    expect(await screen.findByText("Готовый ответ")).toBeInTheDocument();
    expect(source.readyState).toBe(2);
  });

  it("переключает версии ответа «‹ 1/2 ›» и сохраняет выбор", async () => {
    const calls = mockFetch({
      ...COMMON,
      "GET /api/chats/c1": () =>
        json(
          chat(
            [
              message("u", null, "user"),
              message("a1", "u", "assistant"),
              message("a22", "u", "assistant"),
            ],
            "a22",
          ),
        ),
      "PATCH /api/chats/c1": () => json({}),
      "GET /api/auth/csrf": () => json({ csrf_token: "t" }),
    });
    renderApp("/c/c1");
    expect(await screen.findByText("текст a22")).toBeInTheDocument();
    expect(screen.getByTestId("version-label")).toHaveTextContent("2/2");
    await userEvent.click(screen.getByRole("button", { name: "Предыдущая версия" }));
    expect(await screen.findByText("текст a1")).toBeInTheDocument();
    expect(screen.getByTestId("version-label")).toHaveTextContent("1/2");
    const patch = calls.find((c) => c.method === "PATCH");
    expect(await patch?.json()).toEqual({ active_leaf_id: "a1" });
  });
});
