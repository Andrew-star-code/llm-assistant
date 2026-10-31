import { createBrowserRouter, type RouteObject } from "react-router";

import { AdminLayout } from "@/admin/AdminLayout";
import { AdDiagnosticsPage } from "@/admin/pages/AdDiagnosticsPage";
import { AdminHomePage } from "@/admin/pages/AdminHomePage";
import { AuditPage } from "@/admin/pages/AuditPage";
import { LoginsPage } from "@/admin/pages/LoginsPage";
import { UserCardPage } from "@/admin/pages/UserCardPage";
import { UsersPage } from "@/admin/pages/UsersPage";
import { AppLayout } from "@/app/layout/AppLayout";
import { NotFoundPage } from "@/app/layout/NotFoundPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { ChatPage } from "@/features/chat/ChatPage";
import { HomePage } from "@/features/home/HomePage";
import { ProfilePage } from "@/features/profile/ProfilePage";

// Маршруты приложения. Админка — часть того же SPA под /admin с отдельными правами (§13);
// интерфейс прячет недоступное, а права всегда проверяет сервер.
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <HomePage /> },
      { path: "c/:chatId", element: <ChatPage /> },
      { path: "profile", element: <ProfilePage /> },
    ],
  },
  {
    path: "/admin",
    element: (
      <RequireAuth>
        <AdminLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <AdminHomePage /> },
      { path: "users", element: <UsersPage /> },
      { path: "users/:userId", element: <UserCardPage /> },
      { path: "logins", element: <LoginsPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "ad", element: <AdDiagnosticsPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
];

export const router = createBrowserRouter(routes);
