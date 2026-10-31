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

function streamOf(): FakeEventSource {
  const source = FakeEventSource.last;
  if (!source) throw new Error("поток не открыт");
  return source;
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

  it("показывает шаги инструментов и карточку созданного файла", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    FakeEventSource.last = null; // иначе waitFor ниже увидит поток прошлого теста
    let finished = false;
    const streaming = chat(
      [
        message("u", null, "user"),
        message("aa", "u", "assistant", { status: "streaming", content: "" }),
      ],
      "aa",
    );
    const file = {
      id: "f1",
      kind: "generated",
      filename: "Продажи.xlsx",
      mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      file_type: "xlsx",
      size: 2048,
      parse_status: "ready",
      parse_error: null,
      pages: null,
      has_preview: true,
      chat_id: "c1",
      message_id: "aa",
      created_at: "2026-10-31T10:00:00Z",
    };
    const step = {
      call_id: "call_1",
      tool: "create_spreadsheet",
      status: "ok",
      label: "tools.create_spreadsheet",
      params: { name: "Продажи.xlsx" },
      duration_ms: 120,
    };
    const done = chat(
      [
        message("u", null, "user"),
        message("aa", "u", "assistant", {
          content: "Таблица готова",
          files: [file],
          tools: [step],
        }),
      ],
      "aa",
    );
    mockFetch({ ...COMMON, "GET /api/chats/c1": () => json(finished ? done : streaming) });
    renderApp("/c/c1");

    await waitFor(() => {
      expect(FakeEventSource.last?.url).toBe("/api/messages/aa/stream");
    });
    const source = streamOf();
    source.emit("tool.start", {
      call_id: "call_1",
      tool: "create_spreadsheet",
      label: "tools.create_spreadsheet",
      params: { name: "Продажи.xlsx" },
    });
    const running = await screen.findByTestId("tool-step");
    expect(running).toHaveTextContent("Создаю таблицу Продажи.xlsx…");
    expect(running).toHaveAttribute("data-status", "running");

    source.emit("tool.end", { ...step, duration_ms: undefined });
    source.emit("file", {
      file_id: "f1",
      name: "Продажи.xlsx",
      mime: file.mime,
      size: 2048,
      preview: true,
    });
    await waitFor(() => {
      expect(screen.getByTestId("tool-step")).toHaveAttribute("data-status", "ok");
    });
    expect(screen.getByTestId("file-name")).toHaveTextContent("Продажи.xlsx");
    expect(screen.getByRole("link", { name: "Скачать" })).toHaveAttribute(
      "href",
      "/api/files/f1/content",
    );

    finished = true;
    source.emit("message.end", { status: "completed", finish_reason: "stop" });
    // После завершения то же самое строится из REST — и после перезагрузки страницы.
    expect(await screen.findByText("Таблица готова")).toBeInTheDocument();
    expect(screen.getByTestId("tool-step")).toHaveTextContent("Создаю таблицу Продажи.xlsx");
    expect(screen.getByTestId("file-card")).toHaveTextContent("2 КБ");
    expect(screen.getByRole("button", { name: "Просмотр" })).toBeInTheDocument();
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
