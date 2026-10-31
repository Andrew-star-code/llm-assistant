# Справочник конфигурации

> Файл сгенерирован командой `make docs-config` из `backend/app/core/config.py`. Не правьте вручную.

Источники по убыванию приоритета: переменные окружения `APP_*` (вложенность через `__`) →
файлы секретов `/run/secrets/<имя переменной в нижнем регистре>` → `config/app.<env>.yaml` и
`config/models.<env>.yaml` → `config/app.yaml` и `config/models.yaml`.
Секреты (тип `secret`) задаются только через окружение или файлы секретов.

## Приложение

| Параметр | Тип | По умолчанию | Переменная окружения | Описание |
| --- | --- | --- | --- | --- |
| `env` | dev \| test \| prod | `dev` | `APP_ENV` | Окружение: dev \| test \| prod. |
| `app_name` | str | `ИИ-ассистент` | `APP_APP_NAME` | Название в интерфейсе и логах. |
| `config_dir` | Path | `config` | `APP_CONFIG_DIR` | Каталог с YAML-конфигами. |
| `database_url` | secret | — | `APP_DATABASE_URL` | DSN PostgreSQL (секрет: из окружения или /run/secrets/app_database_url). |
| `redis_url` | secret | — | `APP_REDIS_URL` | DSN Redis. |
| `qdrant_url` | str | `http://localhost:6333` | `APP_QDRANT_URL` | HTTP-адрес Qdrant. |
| `qdrant_api_key` | secret \| null | — | `APP_QDRANT_API_KEY` | API-ключ Qdrant (секрет). |
| `readiness_timeout_s` | float | 2.0 | `APP_READINESS_TIMEOUT_S` | Тайм-аут каждой проверки /ready, с. |
| `logging.level` | DEBUG \| INFO \| WARNING \| ERROR | `INFO` | `APP_LOGGING__LEVEL` | Минимальный уровень логов. |
| `logging.format` | json \| console | `json` | `APP_LOGGING__FORMAT` | json — для прода (stdout → сборщик логов), console — для разработки. |
| `auth.providers` | list[ldap \| dev] | ['ldap'] | `APP_AUTH__PROVIDERS` | Провайдеры входа: ldap \| dev. dev запрещён при APP_ENV=prod. |
| `auth.bootstrap_admins` | list[str] | [] | `APP_AUTH__BOOTSTRAP_ADMINS` | Логины первых superadmin; остальные роли — в админке. |
| `auth.session.idle_timeout_minutes` | int | 480 | `APP_AUTH__SESSION__IDLE_TIMEOUT_MINUTES` | Тайм-аут простоя сессии, минут. |
| `auth.session.absolute_timeout_hours` | int | 168 | `APP_AUTH__SESSION__ABSOLUTE_TIMEOUT_HOURS` | Абсолютный срок жизни сессии, ч. |
| `auth.bruteforce.per_login.max_failures` | int | 5 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__MAX_FAILURES` | Сколько неудачных попыток допускается в окне. |
| `auth.bruteforce.per_login.window_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__WINDOW_MINUTES` | Окно подсчёта, минут. |
| `auth.bruteforce.per_login.lock_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__LOCK_MINUTES` | Длительность блокировки, минут. |
| `auth.bruteforce.per_ip.max_failures` | int | 20 | `APP_AUTH__BRUTEFORCE__PER_IP__MAX_FAILURES` | Сколько неудачных попыток допускается в окне. |
| `auth.bruteforce.per_ip.window_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_IP__WINDOW_MINUTES` | Окно подсчёта, минут. |
| `auth.bruteforce.per_ip.lock_minutes` | int | 60 | `APP_AUTH__BRUTEFORCE__PER_IP__LOCK_MINUTES` | Длительность блокировки, минут. |
| `ldap.urls` | list[str] | [] | `APP_LDAP__URLS` | Контроллеры домена по порядку: ldaps://host:636. |
| `ldap.start_tls` | bool | false | `APP_LDAP__START_TLS` | LDAP (389) + StartTLS вместо LDAPS. |
| `ldap.ca_cert_file` | Path \| null | null | `APP_LDAP__CA_CERT_FILE` | Сертификат корпоративного CA. |
| `ldap.bind_dn` | str | "" | `APP_LDAP__BIND_DN` | DN сервисной учётки (только чтение). |
| `ldap.bind_password_file` | Path \| null | null | `APP_LDAP__BIND_PASSWORD_FILE` | Файл с паролем сервисной учётки. |
| `ldap.base_dn` | str | "" | `APP_LDAP__BASE_DN` |  |
| `ldap.user_filter` | str | `(&(objectCategory=person)(objectClass=user)(sAMAccountName={username}))` | `APP_LDAP__USER_FILTER` |  |
| `ldap.upn_suffix` | str | "" | `APP_LDAP__UPN_SUFFIX` |  |
| `ldap.netbios_domain` | str | "" | `APP_LDAP__NETBIOS_DOMAIN` |  |
| `ldap.access_group` | str | "" | `APP_LDAP__ACCESS_GROUP` | DN группы доступа; пусто — пускать всех включённых. |
| `ldap.nested_groups` | bool | true | `APP_LDAP__NESTED_GROUPS` |  |
| `ldap.attributes.guid` | str | `objectGUID` | `APP_LDAP__ATTRIBUTES__GUID` |  |
| `ldap.attributes.login` | str | `sAMAccountName` | `APP_LDAP__ATTRIBUTES__LOGIN` |  |
| `ldap.attributes.email` | str | `mail` | `APP_LDAP__ATTRIBUTES__EMAIL` |  |
| `ldap.attributes.display_name` | str | `displayName` | `APP_LDAP__ATTRIBUTES__DISPLAY_NAME` |  |
| `ldap.attributes.last_name` | str | `sn` | `APP_LDAP__ATTRIBUTES__LAST_NAME` |  |
| `ldap.attributes.first_name` | str | `givenName` | `APP_LDAP__ATTRIBUTES__FIRST_NAME` |  |
| `ldap.attributes.middle_name` | str | `middleName` | `APP_LDAP__ATTRIBUTES__MIDDLE_NAME` | Если пусто — из display_name по шаблону. |
| `ldap.attributes.display_name_pattern` | str | `{last} {first} {middle}` | `APP_LDAP__ATTRIBUTES__DISPLAY_NAME_PATTERN` |  |
| `ldap.attributes.title` | str | `title` | `APP_LDAP__ATTRIBUTES__TITLE` |  |
| `ldap.attributes.department` | str | `department` | `APP_LDAP__ATTRIBUTES__DEPARTMENT` |  |
| `ldap.attributes.company` | str | `company` | `APP_LDAP__ATTRIBUTES__COMPANY` |  |
| `ldap.attributes.office` | str | `physicalDeliveryOfficeName` | `APP_LDAP__ATTRIBUTES__OFFICE` |  |
| `ldap.attributes.phone` | str | `telephoneNumber` | `APP_LDAP__ATTRIBUTES__PHONE` |  |
| `ldap.attributes.mobile` | str | `mobile` | `APP_LDAP__ATTRIBUTES__MOBILE` |  |
| `ldap.attributes.manager` | str | `manager` | `APP_LDAP__ATTRIBUTES__MANAGER` |  |
| `ldap.attributes.employee_id` | str | `employeeID` | `APP_LDAP__ATTRIBUTES__EMPLOYEE_ID` |  |
| `ldap.attributes.photo` | str | `thumbnailPhoto` | `APP_LDAP__ATTRIBUTES__PHOTO` |  |
| `ldap.department_roles.auto` | bool | true | `APP_LDAP__DEPARTMENT_ROLES__AUTO` | Создавать роль «Отдел: <название>» из атрибута department. |
| `ldap.department_roles.rules` | list[AttributeRoleRule] | [] | `APP_LDAP__DEPARTMENT_ROLES__RULES` | Дополнительные роли по значениям атрибутов. |
| `ldap.group_roles` | list[GroupRole] | [] | `APP_LDAP__GROUP_ROLES` |  |
| `ldap.sync_interval_minutes` | int | 60 | `APP_LDAP__SYNC_INTERVAL_MINUTES` |  |
| `models` | dict[str, ModelEndpoint] | {} | `APP_MODELS` | Реестр моделей по ролям (config/models.yaml). |

## Модель в реестре `models.<роль>`

Роли `chat`, `utility`, `embed`, `rerank` обязательны. Переменная окружения: `APP_MODELS__<РОЛЬ>__<ПАРАМЕТР>`, например `APP_MODELS__CHAT__BASE_URL`.

| Параметр | Тип | По умолчанию | Переменная окружения | Описание |
| --- | --- | --- | --- | --- |
| `models.<роль>.base_url` | str | обязательно | — | OpenAI-совместимый эндпоинт, например http://llm-chat:8000/v1 |
| `models.<роль>.model` | str | обязательно | — | Имя модели на эндпоинте. |
| `models.<роль>.api_key` | secret \| null | — | — | Ключ эндпоинта (vLLM --api-key), если есть. |
| `models.<роль>.context_length` | int \| null | null | — | Сколько контекста реально отдаём, а не максимум модели. |
| `models.<роль>.max_output_tokens` | int \| null | null | — |  |
| `models.<роль>.supports_tools` | bool | false | — |  |
| `models.<роль>.thinking.mode` | chat_template_kwarg \| reasoning_effort \| separate_model \| none | `none` | — | Как включается режим размышлений. |
| `models.<роль>.thinking.kwarg` | str | `enable_thinking` | — | Имя флага в chat_template_kwargs. |
| `models.<роль>.thinking.default` | bool | false | — | Включён ли thinking по умолчанию. |
| `models.<роль>.thinking.effort` | low \| medium \| high \| null | null | — | Уровень для mode=reasoning_effort. |
| `models.<роль>.thinking.model_role` | str \| null | null | — | Роль модели для mode=separate_model. |
| `models.<роль>.reasoning_history` | model_default \| drop \| keep | `model_default` | — |  |
| `models.<роль>.sampling.thinking.temperature` | float \| null | null | — |  |
| `models.<роль>.sampling.thinking.top_p` | float \| null | null | — |  |
| `models.<роль>.sampling.thinking.top_k` | int \| null | null | — |  |
| `models.<роль>.sampling.thinking.min_p` | float \| null | null | — |  |
| `models.<роль>.sampling.thinking.presence_penalty` | float \| null | null | — |  |
| `models.<роль>.sampling.thinking.repetition_penalty` | float \| null | null | — |  |
| `models.<роль>.sampling.default.temperature` | float \| null | null | — |  |
| `models.<роль>.sampling.default.top_p` | float \| null | null | — |  |
| `models.<роль>.sampling.default.top_k` | int \| null | null | — |  |
| `models.<роль>.sampling.default.min_p` | float \| null | null | — |  |
| `models.<роль>.sampling.default.presence_penalty` | float \| null | null | — |  |
| `models.<роль>.sampling.default.repetition_penalty` | float \| null | null | — |  |
| `models.<роль>.dim` | int \| null | null | — | Размерность векторов (для embed). |
| `models.<роль>.timeout_s` | float | 600 | — | Тайм-аут запроса к модели, с. |
