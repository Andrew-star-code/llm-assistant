import type { Schemas } from "@/api/client";
/**
 * SSE-клиент потока ответа (docs/architecture/sse-protocol.md, версия 1).
 *
 * EventSource сам переподключается при обрыве сети и передаёт Last-Event-ID — сервер дочитывает
 * пропущенное из Redis Stream. После `message.end` поток закрываем сами, иначе браузер
 * переподключится. Перезагрузка страницы начинает чтение с начала — сервер отдаёт все события.
 */

export const PROTOCOL_VERSION = 1;

export interface ToolStartEvent {
  call_id: string;
  tool: string;
  label: string;
  params: Record<string, string>;
}

export interface ToolEndEvent extends ToolStartEvent {
  status: "ok" | "error" | "timeout";
}

export interface FileEvent {
  file_id: string;
  name: string;
  mime: string;
  size: number;
  preview: boolean;
}

/** Карточка источника (§10.5); событие `sources` всегда несёт полный текущий список. */
export interface SourceCard {
  index: number;
  kind: "kb" | "attachment";
  title: string;
  kb_name: string | null;
  document_id: string | null;
  file_id: string | null;
  page: number | null;
  section: string | null;
  snippet: string;
}

export interface StreamHandlers {
  onStart?: (data: { model: string; thinking: boolean; protocol_version: number }) => void;
  onReasoning?: (text: string) => void;
  onContent?: (text: string) => void;
  onToolStart?: (data: ToolStartEvent) => void;
  onToolEnd?: (data: ToolEndEvent) => void;
  onFile?: (data: FileEvent) => void;
  onSources?: (items: SourceCard[]) => void;
  onUsage?: (data: {
    prompt_tokens: number;
    completion_tokens: number;
    reasoning_tokens: number | null;
  }) => void;
  onTitle?: (data: { chat_id: string; title: string }) => void;
  /** Остатки по лимитам после ответа (§8.5) — то же, что `GET /api/limits`. */
  onLimits?: (data: Schemas["LimitsOut"]) => void;
  onError?: (data: { code: string; message: string; retryable: boolean }) => void;
  onEnd?: (data: { status: string; finish_reason: string | null }) => void;
  /** Поток не открылся совсем (нет прав, сообщение не найдено, сессия истекла). */
  onFatal?: () => void;
}

function parse(event: Event): unknown {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") return null;
  try {
    return JSON.parse(event.data) as unknown;
  } catch {
    return null;
  }
}

/** Паузы переподключения, когда сервер закрыл поток (перезапуск api, 502 прокси). */
export const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 15000, 15000, 15000];
/** Тишина дольше трёх heartbeat (15 с, событие `ping`) — соединение мёртвое, переподключаемся. */
export const SILENCE_TIMEOUT_MS = 45_000;

/**
 * Подписывается на поток ответа; возвращает функцию отписки.
 *
 * Обрыв сети EventSource переживает сам. Но если сервер ответил ошибкой (api перезапускается,
 * прокси вернул 502), EventSource закрывается навсегда — тогда переподключаемся сами с позиции
 * последнего события (`?after=`), с паузами `RECONNECT_DELAYS_MS`. Новый api сам доведёт
 * оборванный ответ до «прервано» (§8.5), и поток закончится событием `message.end`.
 */
export function subscribeMessageStream(messageId: string, handlers: StreamHandlers): () => void {
  let ended = false;
  let lastId = 0;
  let attempt = 0;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let watchdog: ReturnType<typeof setTimeout> | null = null;

  const retry = () => {
    if (ended) return;
    source?.close();
    const delay = RECONNECT_DELAYS_MS[attempt];
    if (delay === undefined) {
      handlers.onFatal?.();
      return;
    }
    attempt += 1;
    timer = setTimeout(() => {
      timer = null;
      if (!ended) open();
    }, delay);
  };

  // Прокси может держать соединение открытым после падения api: без событий и heartbeat
  // EventSource ошибки не увидит — следим за тишиной сами.
  const alive = () => {
    if (watchdog !== null) clearTimeout(watchdog);
    watchdog = setTimeout(() => {
      watchdog = null;
      if (!ended) retry();
    }, SILENCE_TIMEOUT_MS);
  };

  const open = () => {
    const query = lastId > 0 ? `?after=${String(lastId)}` : "";
    const current = new EventSource(`/api/messages/${messageId}/stream${query}`, {
      withCredentials: true,
    });
    source = current;
    alive();
    current.addEventListener("ping", alive);

    // Данные событий — по контракту протокола (docs/architecture/sse-protocol.md).
    const on = (name: string, handler: (data: never) => void) => {
      current.addEventListener(name, (event) => {
        if (event instanceof MessageEvent && event.lastEventId) {
          const seq = Number(event.lastEventId);
          if (Number.isFinite(seq) && seq > lastId) lastId = seq;
        }
        attempt = 0; // поток снова идёт — счётчик попыток с нуля
        alive();
        const data = parse(event);
        if (data !== null) handler(data as never);
      });
    };

    on("message.start", (d: Parameters<NonNullable<StreamHandlers["onStart"]>>[0]) => {
      handlers.onStart?.(d);
    });
    on("reasoning.delta", (d: { text: string }) => {
      handlers.onReasoning?.(d.text);
    });
    on("content.delta", (d: { text: string }) => {
      handlers.onContent?.(d.text);
    });
    on("tool.start", (d: ToolStartEvent) => {
      handlers.onToolStart?.(d);
    });
    on("tool.end", (d: ToolEndEvent) => {
      handlers.onToolEnd?.(d);
    });
    on("file", (d: FileEvent) => {
      handlers.onFile?.(d);
    });
    on("sources", (d: { items: SourceCard[] }) => {
      handlers.onSources?.(d.items);
    });
    on("usage", (d: Parameters<NonNullable<StreamHandlers["onUsage"]>>[0]) => {
      handlers.onUsage?.(d);
    });
    on("limits", (d: Schemas["LimitsOut"]) => {
      handlers.onLimits?.(d);
    });
    on("title", (d: { chat_id: string; title: string }) => {
      handlers.onTitle?.(d);
    });
    on("message.end", (d: { status: string; finish_reason: string | null }) => {
      ended = true;
      if (watchdog !== null) clearTimeout(watchdog);
      current.close();
      handlers.onEnd?.(d);
    });
    // «error» — и событие протокола (с данными), и ошибка соединения EventSource (без данных).
    current.addEventListener("error", (event) => {
      const data = parse(event) as { code: string; message: string; retryable: boolean } | null;
      if (data) {
        if (event instanceof MessageEvent && event.lastEventId) {
          lastId = Math.max(lastId, Number(event.lastEventId) || 0);
        }
        handlers.onError?.(data);
        return;
      }
      if (ended || current.readyState !== EventSource.CLOSED) return;
      retry();
    });
  };

  open();
  return () => {
    ended = true;
    if (timer !== null) clearTimeout(timer);
    if (watchdog !== null) clearTimeout(watchdog);
    source?.close();
  };
}
