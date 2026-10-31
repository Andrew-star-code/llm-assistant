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
| GET | `/api/chats` | `listChats` | List Chats | 200, 422 |
| POST | `/api/chats` | `createChat` | Create Chat | 201, 422 |
| GET | `/api/chats/search` | `searchChats` | Search Chats | 200, 422 |
| GET | `/api/chats/{chat_id}` | `getChat` | Get Chat | 200, 422 |
| PATCH | `/api/chats/{chat_id}` | `updateChat` | Update Chat | 200, 422 |
| DELETE | `/api/chats/{chat_id}` | `deleteChat` | Delete Chat | 204, 422 |
| POST | `/api/chats/{chat_id}/messages` | `sendMessage` | Send Message | 202, 422 |
| POST | `/api/files` | `uploadFile` | Upload | 201, 422 |
| GET | `/api/files/limits` | `getFileLimits` | Limits | 200 |
| GET | `/api/files/{file_id}` | `getFile` | Get File | 200, 422 |
| DELETE | `/api/files/{file_id}` | `deleteFile` | Delete | 204, 422 |
| GET | `/api/files/{file_id}/content` | `downloadFile` | Content | 200, 422 |
| GET | `/api/files/{file_id}/preview` | `previewFile` | Preview | 200, 404, 422 |
| GET | `/api/folders` | `listFolders` | List Folders | 200 |
| POST | `/api/folders` | `createFolder` | Create Folder | 201, 422 |
| PATCH | `/api/folders/{folder_id}` | `updateFolder` | Update Folder | 200, 422 |
| DELETE | `/api/folders/{folder_id}` | `deleteFolder` | Delete Folder | 204, 422 |
| PUT | `/api/messages/{message_id}/feedback` | `setFeedback` | Set Feedback | 200, 422 |
| DELETE | `/api/messages/{message_id}/feedback` | `clearFeedback` | Clear Feedback | 204, 422 |
| POST | `/api/messages/{message_id}/regenerate` | `regenerateMessage` | Regenerate | 202, 422 |
| POST | `/api/messages/{message_id}/stop` | `stopMessage` | Stop | 202, 422 |
| GET | `/api/messages/{message_id}/stream` | `streamMessage` | Stream | 200, 422 |
| GET | `/api/models/chat` | `getChatModel` | Chat Model | 200 |
| GET | `/api/profile` | `getProfile` | Get Profile | 200 |
| GET | `/api/profile/photo` | `getProfilePhoto` | Get Photo | 200, 404 |
| PATCH | `/api/profile/settings` | `updateProfileSettings` | Update Settings | 200, 422 |
| GET | `/health` | `health` | Health | 200 |
| GET | `/ready` | `ready` | Ready | 200, 503 |
