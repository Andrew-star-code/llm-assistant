import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@/api/schema";

export type Schemas = components["schemas"];

const CSRF_COOKIE = "csrftoken";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return null;
}

/** CSRF-токен из cookie; если его ещё нет — сервер выдаёт его на GET /api/auth/csrf. */
export async function csrfToken(): Promise<string> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  const response = await globalThis.fetch(new Request(`${window.location.origin}/api/auth/csrf`));
  const body = (await response.json()) as { csrf_token: string };
  return body.csrf_token;
}

// Double submit (§6.4): каждый изменяющий запрос несёт X-CSRF-Token, равный cookie.
const csrfMiddleware: Middleware = {
  async onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method)) {
      request.headers.set("X-CSRF-Token", await csrfToken());
    }
    return request;
  },
};

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

/** Подписка на 401 от API (сессия истекла или отозвана) — роутер уводит на страницу входа. */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

const unauthorizedMiddleware: Middleware = {
  onResponse({ request, response }) {
    const url = new URL(request.url);
    if (response.status === 401 && !url.pathname.startsWith("/api/auth/")) {
      unauthorizedListeners.forEach((listener) => {
        listener();
      });
    }
    return response;
  },
};

/**
 * Типизированный клиент api. Типы генерируются из OpenAPI бэкенда (`make gen-api`),
 * поэтому фронтенд и бэкенд не расходятся в контракте (§4).
 */
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
  // fetch берётся в момент вызова, а не создания клиента, — так его можно подменить в тестах.
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrfMiddleware, unauthorizedMiddleware);

/** Ошибка API в едином формате бэкенда: {"error": {"code", "message", "request_id"}}. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    /** Подробности ошибки, например `{metric, limit, used, reset_at}` у 429 (§12.3). */
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message);
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: Record<string, unknown> | null };
}

export function toApiError(response: Response, body: unknown): ApiError {
  const error = (body as ErrorBody | undefined)?.error;
  return new ApiError(
    response.status,
    error?.code ?? "unknown",
    error?.message ?? response.statusText,
    error?.details ?? null,
  );
}

/** Распаковывает ответ openapi-fetch: данные или ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    if (result.response.ok) return undefined as T; // 204 No Content
    throw toApiError(result.response, result.error);
  }
  return result.data;
}
