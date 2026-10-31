import { createBrowserRouter, type RouteObject } from "react-router";

import { AdminLayout } from "@/admin/AdminLayout";
import { AdminHomePage } from "@/admin/pages/AdminHomePage";
import { AppLayout } from "@/app/layout/AppLayout";
import { NotFoundPage } from "@/app/layout/NotFoundPage";
import { HomePage } from "@/features/home/HomePage";

// Маршруты приложения. Админка — часть того же SPA под /admin с отдельными правами (§13);
// проверка прав появится на этапе 1, сервер проверяет права всегда сам.
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [{ index: true, element: <HomePage /> }],
  },
  {
    path: "/admin",
    element: <AdminLayout />,
    children: [{ index: true, element: <AdminHomePage /> }],
  },
  { path: "*", element: <NotFoundPage /> },
];

export const router = createBrowserRouter(routes);
