import createClient from "openapi-fetch";

import type { paths } from "@/api/schema";

/**
 * Типизированный клиент api. Типы генерируются из OpenAPI бэкенда (`make gen-api`),
 * поэтому фронтенд и бэкенд не расходятся в контракте (§4).
 * Cookie сессии отправляются автоматически (same-origin); CSRF-заголовок добавится на этапе 1.
 */
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
  // fetch берётся в момент вызова, а не создания клиента, — так его можно подменить в тестах.
  fetch: (request) => globalThis.fetch(request),
});
