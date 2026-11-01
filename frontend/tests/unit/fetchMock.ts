import { vi } from "vitest";

export type Handler = (request: Request) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Подменяет fetch: ключ — «МЕТОД /путь», неизвестный маршрут — 404. Возвращает журнал запросов. */
export function mockFetch(routes: Record<string, Handler>): Request[] {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const request = input instanceof Request ? input : new Request(input);
      calls.push(request);
      const key = `${request.method} ${new URL(request.url).pathname}`;
      const handler = routes[key];
      return handler ? handler(request) : json({ error: { code: "not_found", message: key } }, 404);
    }),
  );
  return calls;
}

export const ME = {
  id: "00000000-0000-0000-0000-000000000001",
  login: "petrov",
  full_name: "Петров Сергей Алексеевич",
  first_name: "Сергей",
  middle_name: "Алексеевич",
  address: "Сергей Алексеевич",
  title: "Бухгалтер",
  department: "Бухгалтерия",
  has_photo: false,
  roles: [
    { code: "dept:Бухгалтерия", name: "Отдел: Бухгалтерия", kind: "department", source: "ad" },
  ],
  permissions: [] as string[],
  settings: { theme: null },
  notice: { required: false, text: "Переписка сохраняется." },
};

export const ADMIN_ME = {
  ...ME,
  login: "ivanov",
  full_name: "Иванов Иван Петрович",
  address: "Иван Петрович",
  permissions: ["admin.access", "admin.users.view", "admin.audit.view"],
};
