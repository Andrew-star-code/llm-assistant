# Справочник API

> Файл сгенерирован командой `make gen-api` из OpenAPI бэкенда. Не правьте вручную.
> Полная схема — `frontend/src/api/openapi.json`; интерактивно в dev — `/api/docs`.

| Метод | Путь | operationId | Описание | Ответы |
| --- | --- | --- | --- | --- |
| POST | `/api/admin/ad/diagnostics` | `adminAdDiagnostics` | Ad Diagnostics | 200, 422 |
| GET | `/api/admin/audit` | `adminListAudit` | List Audit | 200, 422 |
| GET | `/api/admin/logins` | `adminListLogins` | List Logins | 200, 422 |
| GET | `/api/admin/roles` | `adminListRoles` | List Roles | 200 |
| DELETE | `/api/admin/sessions/{session_id}` | `adminRevokeSession` | Revoke Session | 204, 422 |
| GET | `/api/admin/users` | `adminListUsers` | List Users | 200, 422 |
| GET | `/api/admin/users/{user_id}` | `adminGetUser` | Get User | 200, 422 |
| POST | `/api/admin/users/{user_id}/block` | `adminBlockUser` | Block User | 200, 422 |
| POST | `/api/admin/users/{user_id}/logout` | `adminLogoutUser` | Logout User | 200, 422 |
| GET | `/api/admin/users/{user_id}/photo` | `adminGetUserPhoto` | Get User Photo | 200, 404, 422 |
| PUT | `/api/admin/users/{user_id}/roles` | `adminSetUserRoles` | Set User Roles | 200, 422 |
| POST | `/api/admin/users/{user_id}/unblock` | `adminUnblockUser` | Unblock User | 204, 422 |
| GET | `/api/auth/csrf` | `getCsrfToken` | Csrf | 200 |
| POST | `/api/auth/login` | `login` | Login | 200, 401, 422 |
| POST | `/api/auth/logout` | `logout` | Logout | 204 |
| GET | `/api/auth/me` | `getMe` | Me | 200 |
| POST | `/api/auth/notice/accept` | `acceptNotice` | Accept Notice | 204 |
| GET | `/api/auth/providers` | `getAuthProviders` | Providers | 200 |
| GET | `/api/profile` | `getProfile` | Get Profile | 200 |
| GET | `/api/profile/photo` | `getProfilePhoto` | Get Photo | 200, 404 |
| PATCH | `/api/profile/settings` | `updateProfileSettings` | Update Settings | 200, 422 |
| GET | `/health` | `health` | Health | 200 |
| GET | `/ready` | `ready` | Ready | 200, 503 |
