/**
 * SSE-клиент потока ответа (docs/architecture/sse-protocol.md, версия 1).
 *
 * EventSource сам переподключается при обрыве сети и передаёт Last-Event-ID — сервер дочитывает
 * пропущенное из Redis Stream. После `message.end` поток закрываем сами, иначе браузер
 * переподключится. Перезагрузка страницы начинает чтение с начала — сервер отдаёт все события.
 */

export const PROTOCOL_VERSION = 1;

export interface StreamHandlers {
  onStart?: (data: { model: string; thinking: boolean; protocol_version: number }) => void;
  onReasoning?: (text: string) => void;
  onContent?: (text: string) => void;
  onUsage?: (data: {
    prompt_tokens: number;
    completion_tokens: number;
    reasoning_tokens: number | null;
  }) => void;
  onTitle?: (data: { chat_id: string; title: string }) => void;
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

/** Подписывается на поток ответа; возвращает функцию отписки. */
export function subscribeMessageStream(messageId: string, handlers: StreamHandlers): () => void {
  const source = new EventSource(`/api/messages/${messageId}/stream`, { withCredentials: true });
  let ended = false;

  // Данные событий — по контракту протокола (docs/architecture/sse-protocol.md).
  const on = (name: string, handler: (data: never) => void) => {
    source.addEventListener(name, (event) => {
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
  on("usage", (d: Parameters<NonNullable<StreamHandlers["onUsage"]>>[0]) => {
    handlers.onUsage?.(d);
  });
  on("title", (d: { chat_id: string; title: string }) => {
    handlers.onTitle?.(d);
  });
  on("message.end", (d: { status: string; finish_reason: string | null }) => {
    ended = true;
    source.close();
    handlers.onEnd?.(d);
  });
  // «error» — и событие протокола (с данными), и ошибка соединения EventSource (без данных).
  source.addEventListener("error", (event) => {
    const data = parse(event) as { code: string; message: string; retryable: boolean } | null;
    if (data) {
      handlers.onError?.(data);
      return;
    }
    if (!ended && source.readyState === EventSource.CLOSED) handlers.onFatal?.();
  });

  return () => {
    ended = true;
    source.close();
  };
}
