# Справочник API

> Файл сгенерирован командой `make gen-api` из OpenAPI бэкенда. Не правьте вручную.
> Полная схема — `frontend/src/api/openapi.json`; интерактивно в dev — `/api/docs`.

| Метод | Путь | operationId | Описание | Ответы |
| --- | --- | --- | --- | --- |
| POST | `/api/admin/ad/diagnostics` | `adminAdDiagnostics` | Ad Diagnostics | 200, 422 |
| GET | `/api/admin/audit` | `adminListAudit` | List Audit | 200, 422 |
| GET | `/api/admin/chats` | `adminListChats` | List Chats | 200, 422 |
| GET | `/api/admin/chats/filters` | `adminChatFilterOptions` | Filter Options | 200 |
| GET | `/api/admin/chats/{chat_id}` | `adminGetChat` | Get Chat | 200, 422 |
| POST | `/api/admin/chats/{chat_id}/purge` | `adminPurgeChat` | Purge | 200, 422 |
| POST | `/api/admin/chats/{chat_id}/restore` | `adminRestoreChat` | Restore Chat | 200, 422 |
| GET | `/api/admin/dashboard` | `adminDashboard` | Dashboard | 200, 422 |
| GET | `/api/admin/exports` | `adminListExports` | List Exports | 200 |
| POST | `/api/admin/exports` | `adminCreateExport` | Create Export | 202, 422 |
| GET | `/api/admin/exports/{export_id}` | `adminGetExport` | Get Export | 200, 422 |
| GET | `/api/admin/exports/{export_id}/download` | `adminDownloadExport` | Download Export | 200, 422 |
| GET | `/api/admin/feedback` | `adminListFeedback` | List Feedback | 200, 422 |
| GET | `/api/admin/feedback/export` | `adminExportFeedback` | Export Feedback | 200, 422 |
| GET | `/api/admin/feedback/stats` | `adminFeedbackStats` | Stats | 200, 422 |
| GET | `/api/admin/incidents` | `adminListIncidents` | List Incidents | 200, 422 |
| GET | `/api/admin/kb` | `adminListKb` | List Bases | 200 |
| POST | `/api/admin/kb` | `adminCreateKb` | Create Base | 201, 422 |
| GET | `/api/admin/kb/import-folders` | `adminImportFolders` | Import Folders | 200 |
| GET | `/api/admin/kb/search-settings` | `adminKbSearchSettings` | Get Search Settings | 200 |
| PUT | `/api/admin/kb/search-settings` | `adminUpdateKbSearchSettings` | Update Search Settings | 200, 422 |
| PATCH | `/api/admin/kb/{kb_id}` | `adminUpdateKb` | Update Base | 200, 422 |
| DELETE | `/api/admin/kb/{kb_id}` | `adminDeleteKb` | Delete Base | 204, 422 |
| GET | `/api/admin/kb/{kb_id}/documents` | `adminKbDocuments` | List Documents | 200, 422 |
| POST | `/api/admin/kb/{kb_id}/documents` | `adminUploadKbDocument` | Upload Document | 201, 422 |
| DELETE | `/api/admin/kb/{kb_id}/documents/{document_id}` | `adminDeleteKbDocument` | Delete Kb Document | 204, 422 |
| POST | `/api/admin/kb/{kb_id}/documents/{document_id}/reindex` | `adminReindexKbDocument` | Reindex Document | 200, 422 |
| GET | `/api/admin/kb/{kb_id}/imports` | `adminKbImports` | List Imports | 200, 422 |
| POST | `/api/admin/kb/{kb_id}/imports` | `adminStartImport` | Start Import | 202, 422 |
| GET | `/api/admin/logins` | `adminListLogins` | List Logins | 200, 422 |
| GET | `/api/admin/messages` | `adminSearchMessages` | Search Messages | 200, 422 |
| GET | `/api/admin/models` | `adminListModels` | List Models | 200 |
| GET | `/api/admin/models/health` | `adminModelsHealth` | Models Health | 200 |
| PUT | `/api/admin/models/{role}/visibility` | `adminSetModelVisibility` | Set Visibility | 200, 422 |
| GET | `/api/admin/roles` | `adminListRoles` | List Roles | 200 |
| POST | `/api/admin/roles` | `adminCreateRole` | Create Role | 201, 422 |
| GET | `/api/admin/roles/{role_id}` | `adminGetRole` | Get Role | 200, 422 |
| PATCH | `/api/admin/roles/{role_id}` | `adminUpdateRole` | Update Role | 200, 422 |
| DELETE | `/api/admin/roles/{role_id}` | `adminDeleteRole` | Delete Role | 204, 422 |
| GET | `/api/admin/roles/{role_id}/members` | `adminRoleMembers` | Members | 200, 422 |
| POST | `/api/admin/roles/{role_id}/members` | `adminAddRoleMembers` | Add Members | 200, 422 |
| POST | `/api/admin/roles/{role_id}/members/remove` | `adminRemoveRoleMembers` | Remove Members | 200, 422 |
| GET | `/api/admin/scenarios` | `adminListScenarios` | List Scenarios | 200 |
| POST | `/api/admin/scenarios` | `adminCreateScenario` | Create Scenario | 201, 422 |
| GET | `/api/admin/scenarios/options` | `adminScenarioOptions` | Options | 200 |
| GET | `/api/admin/scenarios/{scenario_id}` | `adminGetScenario` | Get Scenario | 200, 422 |
| PUT | `/api/admin/scenarios/{scenario_id}` | `adminUpdateScenario` | Update Scenario | 200, 422 |
| DELETE | `/api/admin/scenarios/{scenario_id}` | `adminDeleteScenario` | Delete Scenario | 204, 422 |
| POST | `/api/admin/scenarios/{scenario_id}/test-chat` | `adminScenarioTestChat` | Test Chat | 201, 422 |
| DELETE | `/api/admin/sessions/{session_id}` | `adminRevokeSession` | Revoke Session | 204, 422 |
| GET | `/api/admin/settings` | `adminGetSettings` | Get Settings | 200 |
| PUT | `/api/admin/settings` | `adminUpdateSettings` | Update Settings | 200, 422 |
| POST | `/api/admin/settings/logo` | `adminUploadLogo` | Upload Logo | 200, 422 |
| DELETE | `/api/admin/settings/logo` | `adminDeleteLogo` | Delete Logo | 200 |
| GET | `/api/admin/tools` | `adminListTools` | List Tools | 200 |
| PUT | `/api/admin/tools/{name}` | `adminToggleTool` | Toggle Tool | 200, 422 |
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
| GET | `/api/branding` | `getBranding` | Branding | 200 |
| GET | `/api/branding/logo` | `getBrandingLogo` | Logo | 200 |
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
| GET | `/api/kb/documents/{document_id}` | `getKbDocument` | Document | 200, 422 |
| GET | `/api/kb/documents/{document_id}/content` | `downloadKbDocument` | Document Content | 200, 422 |
| GET | `/api/kb/documents/{document_id}/preview` | `previewKbDocument` | Document Preview | 200, 404, 422 |
| GET | `/api/kb/personal` | `getPersonalKb` | Personal | 200 |
| POST | `/api/kb/personal/documents` | `uploadPersonalDocument` | Upload Personal | 201, 422 |
| DELETE | `/api/kb/personal/documents/{document_id}` | `deletePersonalDocument` | Delete Personal | 204, 422 |
| POST | `/api/kb/personal/documents/{document_id}/reindex` | `reindexPersonalDocument` | Reindex Personal | 200, 422 |
| PUT | `/api/messages/{message_id}/feedback` | `setFeedback` | Set Feedback | 200, 422 |
| DELETE | `/api/messages/{message_id}/feedback` | `clearFeedback` | Clear Feedback | 204, 422 |
| POST | `/api/messages/{message_id}/regenerate` | `regenerateMessage` | Regenerate | 202, 422 |
| POST | `/api/messages/{message_id}/stop` | `stopMessage` | Stop | 202, 422 |
| GET | `/api/messages/{message_id}/stream` | `streamMessage` | Stream | 200, 422 |
| GET | `/api/models/chat` | `getChatModel` | Chat Model | 200 |
| GET | `/api/profile` | `getProfile` | Get Profile | 200 |
| GET | `/api/profile/photo` | `getProfilePhoto` | Get Photo | 200, 404 |
| PATCH | `/api/profile/settings` | `updateProfileSettings` | Update Settings | 200, 422 |
| GET | `/api/scenarios` | `listScenarios` | List Scenarios | 200 |
| GET | `/health` | `health` | Health | 200 |
| GET | `/ready` | `ready` | Ready | 200, 503 |
