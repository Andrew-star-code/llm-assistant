import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { Providers } from "@/app/providers";
import { routes } from "@/app/router";

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}
