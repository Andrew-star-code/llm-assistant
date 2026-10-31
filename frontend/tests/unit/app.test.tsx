import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { routes } from "@/app/router";

describe("SPA", () => {
  it("рендерит каркас и стартовый экран", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ status: "ready", checks: {} })))),
    );
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(
      <Providers>
        <RouterProvider router={router} />
      </Providers>,
    );
    expect(screen.getByRole("complementary", { name: "Боковая панель" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/!/);
    expect(await screen.findByText("API готов")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("показывает 404 для неизвестного адреса", () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/nope"] });
    render(
      <Providers>
        <RouterProvider router={router} />
      </Providers>,
    );
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
  });
});
