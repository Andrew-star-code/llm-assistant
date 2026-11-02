import { afterEach, describe, expect, it, vi } from "vitest";

import { RECONNECT_DELAYS_MS, SILENCE_TIMEOUT_MS, subscribeMessageStream } from "@/api/sse";

type Listener = (event: Event) => void;

/** EventSource, которым управляет тест: события протокола и «сервер закрыл соединение». */
class FakeSource {
  static all: FakeSource[] = [];
  static CLOSED = 2;
  readyState = 1;
  listeners = new Map<string, Listener[]>();
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  addEventListener(name: string, listener: Listener) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }
  emit(name: string, id: number, data: unknown) {
    const event = new MessageEvent(name, { data: JSON.stringify(data), lastEventId: String(id) });
    this.listeners.get(name)?.forEach((l) => {
      l(event);
    });
  }
  fail() {
    this.readyState = 2;
    this.listeners.get("error")?.forEach((l) => {
      l(new Event("error"));
    });
  }
  close() {
    this.readyState = 2;
  }
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeSource.all = [];
});

describe("поток ответа", () => {
  it("после закрытия сервером переподключается с последнего события и дочитывает конец", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
    const content: string[] = [];
    const errors: string[] = [];
    const ends: string[] = [];
    const fatal = vi.fn();
    subscribeMessageStream("m1", {
      onContent: (text) => content.push(text),
      onError: (e) => errors.push(e.code),
      onEnd: (e) => ends.push(e.status),
      onFatal: fatal,
    });
    const first = FakeSource.all[0];
    expect(first?.url).toBe("/api/messages/m1/stream");
    first?.emit("content.delta", 2, { text: "Слово1 " });
    first?.fail(); // api перезапускается: прокси ответил 502, EventSource закрылся навсегда
    expect(FakeSource.all).toHaveLength(1);
    vi.advanceTimersByTime(RECONNECT_DELAYS_MS[0] ?? 0);
    const second = FakeSource.all[1];
    expect(second?.url).toBe("/api/messages/m1/stream?after=2");
    second?.fail(); // api ещё не поднялся
    vi.advanceTimersByTime(RECONNECT_DELAYS_MS[1] ?? 0);
    const third = FakeSource.all[2];
    third?.emit("error", 3, {
      code: "interrupted",
      message: "Генерация прервана",
      retryable: true,
    });
    third?.emit("message.end", 4, { status: "interrupted", finish_reason: null });
    expect(content).toEqual(["Слово1 "]);
    expect(errors).toEqual(["interrupted"]);
    expect(ends).toEqual(["interrupted"]);
    expect(fatal).not.toHaveBeenCalled();
  });

  it("после всех попыток — onFatal; отписка останавливает переподключение", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
    const fatal = vi.fn();
    subscribeMessageStream("m2", { onFatal: fatal });
    for (const delay of RECONNECT_DELAYS_MS) {
      FakeSource.all.at(-1)?.fail();
      vi.advanceTimersByTime(delay);
    }
    FakeSource.all.at(-1)?.fail();
    expect(fatal).toHaveBeenCalledOnce();
    expect(FakeSource.all).toHaveLength(RECONNECT_DELAYS_MS.length + 1);

    const unsubscribe = subscribeMessageStream("m3", { onFatal: fatal });
    FakeSource.all.at(-1)?.fail();
    unsubscribe();
    vi.advanceTimersByTime(60_000);
    expect(FakeSource.all.filter((s) => s.url.includes("m3"))).toHaveLength(1);
  });

  it("тишина дольше трёх heartbeat — переподключение, ping продлевает соединение", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
    subscribeMessageStream("m4", {});
    const first = FakeSource.all[0];
    first?.emit("content.delta", 5, { text: "x" });
    vi.advanceTimersByTime(SILENCE_TIMEOUT_MS - 1000);
    first?.emit("ping", 0, {}); // сервер жив
    vi.advanceTimersByTime(SILENCE_TIMEOUT_MS - 1000);
    expect(FakeSource.all).toHaveLength(1);
    // Прокси держит соединение, а api уже нет: событий нет — закрываем и переподключаемся.
    vi.advanceTimersByTime(1000 + (RECONNECT_DELAYS_MS[0] ?? 0));
    expect(first?.readyState).toBe(2);
    expect(FakeSource.all[1]?.url).toBe("/api/messages/m4/stream?after=5");
  });
});
