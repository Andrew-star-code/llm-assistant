import { createBrowserRouter, type RouteObject } from "react-router";

import { AdminLayout } from "@/admin/AdminLayout";
import { AdDiagnosticsPage } from "@/admin/pages/AdDiagnosticsPage";
import { AdminChatPage } from "@/admin/pages/AdminChatPage";
import { AdminHomePage } from "@/admin/pages/AdminHomePage";
import { AuditPage } from "@/admin/pages/AuditPage";
import { ChatsPage } from "@/admin/pages/ChatsPage";
import { DashboardPage } from "@/admin/pages/DashboardPage";
import { ExportsPage } from "@/admin/pages/ExportsPage";
import { FeedbackPage } from "@/admin/pages/FeedbackPage";
import { IncidentPage } from "@/admin/pages/IncidentPage";
import { IncidentsPage } from "@/admin/pages/IncidentsPage";
import { KbBasePage } from "@/admin/pages/KbBasePage";
import { KbListPage } from "@/admin/pages/KbListPage";
import { ScenarioEditorPage } from "@/admin/pages/ScenarioEditorPage";
import { ScenarioListPage } from "@/admin/pages/ScenarioListPage";
import { LimitsPage } from "@/admin/pages/LimitsPage";
import { LoginsPage } from "@/admin/pages/LoginsPage";
import { ModelsPage } from "@/admin/pages/ModelsPage";
import { RolePage } from "@/admin/pages/RolePage";
import { RolesPage } from "@/admin/pages/RolesPage";
import { SecurityPage } from "@/admin/pages/SecurityPage";
import { SettingsPage } from "@/admin/pages/SettingsPage";
import { ToolsPage } from "@/admin/pages/ToolsPage";
import { UserCardPage } from "@/admin/pages/UserCardPage";
import { UsersPage } from "@/admin/pages/UsersPage";
import { AppLayout } from "@/app/layout/AppLayout";
import { NotFoundPage } from "@/app/layout/NotFoundPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { ChatPage } from "@/features/chat/ChatPage";
import { HomePage } from "@/features/home/HomePage";
import { PersonalKbPage } from "@/features/kb/PersonalKbPage";
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
      { path: "kb", element: <PersonalKbPage /> },
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
      { path: "kb", element: <KbListPage /> },
      { path: "kb/:kbId", element: <KbBasePage /> },
      { path: "incidents", element: <IncidentsPage /> },
      { path: "incidents/:incidentId", element: <IncidentPage /> },
      { path: "security", element: <SecurityPage /> },
      { path: "limits", element: <LimitsPage /> },
      { path: "scenarios", element: <ScenarioListPage /> },
      { path: "scenarios/:scenarioId", element: <ScenarioEditorPage /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "roles", element: <RolesPage /> },
      { path: "roles/:roleId", element: <RolePage /> },
      { path: "chats", element: <ChatsPage /> },
      { path: "chats/:chatId", element: <AdminChatPage /> },
      { path: "exports", element: <ExportsPage /> },
      { path: "feedback", element: <FeedbackPage /> },
      { path: "models", element: <ModelsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
];

export const router = createBrowserRouter(routes);
