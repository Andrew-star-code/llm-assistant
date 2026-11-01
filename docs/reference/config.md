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
| `trusted_proxies` | list[str] | [] | `APP_TRUSTED_PROXIES` | IP прокси (nginx), чьему X-Forwarded-For доверяем при определении IP клиента. |
| `logging.level` | DEBUG \| INFO \| WARNING \| ERROR | `INFO` | `APP_LOGGING__LEVEL` | Минимальный уровень логов. |
| `logging.format` | json \| console | `json` | `APP_LOGGING__FORMAT` | json — для прода (stdout → сборщик логов), console — для разработки. |
| `auth.providers` | list[ldap \| dev] | ['ldap'] | `APP_AUTH__PROVIDERS` | Провайдеры входа: ldap \| dev. dev запрещён при APP_ENV=prod. |
| `auth.bootstrap_admins` | list[str] | [] | `APP_AUTH__BOOTSTRAP_ADMINS` | Логины первых superadmin; остальные роли — в админке. |
| `auth.session.idle_timeout_minutes` | int | 480 | `APP_AUTH__SESSION__IDLE_TIMEOUT_MINUTES` | Тайм-аут простоя сессии, минут. |
| `auth.session.absolute_timeout_hours` | int | 168 | `APP_AUTH__SESSION__ABSOLUTE_TIMEOUT_HOURS` | Абсолютный срок жизни сессии, ч. |
| `auth.session.cookie_name` | str | `sid` | `APP_AUTH__SESSION__COOKIE_NAME` | Имя cookie сессии (HttpOnly). |
| `auth.session.csrf_cookie_name` | str | `csrftoken` | `APP_AUTH__SESSION__CSRF_COOKIE_NAME` | Имя cookie CSRF-токена (читается JS). |
| `auth.session.cookie_secure` | bool | true | `APP_AUTH__SESSION__COOKIE_SECURE` | Флаг Secure у cookie; false — только для dev по http. |
| `auth.bruteforce.per_login.max_failures` | int | 5 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__MAX_FAILURES` | Сколько неудачных попыток допускается в окне. |
| `auth.bruteforce.per_login.window_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__WINDOW_MINUTES` | Окно подсчёта, минут. |
| `auth.bruteforce.per_login.lock_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_LOGIN__LOCK_MINUTES` | Длительность блокировки, минут. |
| `auth.bruteforce.per_ip.max_failures` | int | 20 | `APP_AUTH__BRUTEFORCE__PER_IP__MAX_FAILURES` | Сколько неудачных попыток допускается в окне. |
| `auth.bruteforce.per_ip.window_minutes` | int | 15 | `APP_AUTH__BRUTEFORCE__PER_IP__WINDOW_MINUTES` | Окно подсчёта, минут. |
| `auth.bruteforce.per_ip.lock_minutes` | int | 60 | `APP_AUTH__BRUTEFORCE__PER_IP__LOCK_MINUTES` | Длительность блокировки, минут. |
| `auth.dev_users` | list[DevUser] | [] | `APP_AUTH__DEV_USERS` | Seed-пользователи провайдера dev (только разработка). |
| `auth.first_login_notice` | str | `Переписка с ассистентом сохраняется и может проверяться администраторами в соответствии с политикой компании. Не передавайте ассистенту пароли и чужие персональные данные.` | `APP_AUTH__FIRST_LOGIN_NOTICE` | Текст уведомления при первом входе по умолчанию; меняется в админке (§15). |
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
| `ldap.sync_interval_minutes` | int | 60 | `APP_LDAP__SYNC_INTERVAL_MINUTES` | Период синхронизации; 0 — выключена. |
| `ldap.timeout_s` | float | 5.0 | `APP_LDAP__TIMEOUT_S` | Тайм-аут подключения и запроса к AD, с. |
| `users.default_address_form` | name_patronymic \| first_name \| full_name \| formal | `name_patronymic` | `APP_USERS__DEFAULT_ADDRESS_FORM` | Форма обращения по умолчанию (§11.1): name_patronymic — «Имя Отчество», first_name — «Имя», full_name — «Фамилия Имя Отчество», formal — «на вы» без имени. |
| `storage.root` | Path | `/srv/storage` | `APP_STORAGE__ROOT` | Каталог тома с файлами (фото, загрузки, документы). |
| `chat.company_name` | str | `Компания` | `APP_CHAT__COMPANY_NAME` | Название компании в системном промпте. |
| `chat.timezone` | str | `Europe/Moscow` | `APP_CHAT__TIMEZONE` | Часовой пояс компании: дата и время в промпте, группы чатов. |
| `chat.max_message_chars` | int | 32000 | `APP_CHAT__MAX_MESSAGE_CHARS` | Максимальная длина сообщения, симв. |
| `chat.stream_ttl_seconds` | int | 600 | `APP_CHAT__STREAM_TTL_SECONDS` | Сколько поток генерации хранится в Redis после завершения (§8.5). |
| `chat.heartbeat_seconds` | int | 15 | `APP_CHAT__HEARTBEAT_SECONDS` | Интервал heartbeat в SSE, с. |
| `chat.title_timeout_seconds` | float | 15 | `APP_CHAT__TITLE_TIMEOUT_SECONDS` | Тайм-аут генерации заголовка, с. |
| `files.max_file_mb` | int | 50 | `APP_FILES__MAX_FILE_MB` | Максимальный размер файла, МБ. |
| `files.max_files_per_message` | int | 10 | `APP_FILES__MAX_FILES_PER_MESSAGE` | Сколько файлов можно приложить. |
| `files.max_unpacked_mb` | int | 300 | `APP_FILES__MAX_UNPACKED_MB` | Лимит распакованного объёма DOCX/XLSX/PPTX/ODF (защита от zip-бомб). |
| `files.max_compression_ratio` | int | 100 | `APP_FILES__MAX_COMPRESSION_RATIO` | Максимальный коэффициент сжатия записи архива. |
| `files.max_archive_entries` | int | 5000 | `APP_FILES__MAX_ARCHIVE_ENTRIES` | Максимум файлов внутри архива. |
| `files.max_pages` | int | 1000 | `APP_FILES__MAX_PAGES` | Лимит страниц разбираемого документа. |
| `files.max_text_chars` | int | 5000000 | `APP_FILES__MAX_TEXT_CHARS` | Лимит извлечённого текста; дальше документ обрезается. |
| `files.parse_timeout_seconds` | int | 600 | `APP_FILES__PARSE_TIMEOUT_SECONDS` | Тайм-аут разбора одного файла, с. |
| `files.convert_timeout_seconds` | int | 180 | `APP_FILES__CONVERT_TIMEOUT_SECONDS` | Тайм-аут одной конвертации LibreOffice, с. |
| `files.ocr_languages` | str | `rus+eng` | `APP_FILES__OCR_LANGUAGES` | Языки Tesseract для сканов. |
| `files.ocr_min_chars_per_page` | int | 30 | `APP_FILES__OCR_MIN_CHARS_PER_PAGE` | Меньше символов на странице PDF — считаем её сканом и делаем OCR. |
| `files.full_text_budget_share` | float | 0.3 | `APP_FILES__FULL_TEXT_BUDGET_SHARE` | Вложения целиком в промпт, если занимают меньше этой доли. |
| `files.outline_preview_chars` | int | 6000 | `APP_FILES__OUTLINE_PREVIEW_CHARS` | Сколько первых символов большого документа идёт в промпт. |
| `files.docling_enabled` | bool | false | `APP_FILES__DOCLING_ENABLED` | Разбирать документы docling (модели — локально, этап 10). |
| `tools.enabled` | list[str] \| null | null | `APP_TOOLS__ENABLED` | Включённые инструменты; null — все зарегистрированные (§13.2 — этап 6). |
| `tools.max_iterations` | int | 8 | `APP_TOOLS__MAX_ITERATIONS` | Максимум итераций цикла инструментов. |
| `tools.result_max_chars` | int | 20000 | `APP_TOOLS__RESULT_MAX_CHARS` | Результат инструмента обрезается до этой длины для модели. |
| `worker.broker_db` | int | 1 | `APP_WORKER__BROKER_DB` | Номер БД Redis для брокера Celery. |
| `worker.task_timeout_seconds` | int | 300 | `APP_WORKER__TASK_TIMEOUT_SECONDS` | Сколько api ждёт задачу воркера (генерация файла), с. |
| `worker.eager` | bool | false | `APP_WORKER__EAGER` | Выполнять задачи в процессе api (только тесты). |
| `rag.mode` | auto \| tool \| off | `auto` | `APP_RAG__MODE` | Режим RAG по умолчанию (дальше — из сценария, этап 5). |
| `rag.search.prefetch.dense` | int | 40 | `APP_RAG__SEARCH__PREFETCH__DENSE` | Кандидатов из векторного поиска в каждой коллекции. |
| `rag.search.prefetch.bm25` | int | 40 | `APP_RAG__SEARCH__PREFETCH__BM25` | Кандидатов из BM25 в каждой коллекции. |
| `rag.search.fusion` | rrf \| dbsf | `rrf` | `APP_RAG__SEARCH__FUSION` | Слияние списков dense и BM25. |
| `rag.search.rrf_k` | int | 60 | `APP_RAG__SEARCH__RRF_K` | Константа RRF: 1 / (k + ранг). |
| `rag.search.bm25.provider` | qdrant | `qdrant` | `APP_RAG__SEARCH__BM25__PROVIDER` | qdrant — BM25 считает сам Qdrant (≥ 1.15.3). |
| `rag.search.bm25.model` | str | `qdrant/bm25` | `APP_RAG__SEARCH__BM25__MODEL` | Модель BM25 в Qdrant. |
| `rag.search.bm25.language` | str | `russian` | `APP_RAG__SEARCH__BM25__LANGUAGE` | Язык стемминга и стоп-слов. |
| `rag.search.bm25.avg_len` | float | 400 | `APP_RAG__SEARCH__BM25__AVG_LEN` | Средняя длина чанка в словах (подбирается на выборке и eval). |
| `rag.search.rerank.enabled` | bool | true | `APP_RAG__SEARCH__RERANK__ENABLED` | Выключать только в eval и при отладке (§10.4). |
| `rag.search.rerank.max_candidates` | int | 60 | `APP_RAG__SEARCH__RERANK__MAX_CANDIDATES` | Сколько лучших по RRF уходит в реранкер. |
| `rag.search.rerank.score_threshold` | float | 0.005 | `APP_RAG__SEARCH__RERANK__SCORE_THRESHOLD` | Отсечение по баллу реранкера (админка может переопределить без перезапуска). |
| `rag.search.rerank.timeout_s` | float | 3 | `APP_RAG__SEARCH__RERANK__TIMEOUT_S` | Ждём реранкер не дольше, с. |
| `rag.search.max_per_document` | int | 3 | `APP_RAG__SEARCH__MAX_PER_DOCUMENT` | Не больше фрагментов с одного документа. |
| `rag.search.final_k` | int | 8 | `APP_RAG__SEARCH__FINAL_K` | Итоговое число фрагментов. |
| `rag.search.fallback_k` | int | 6 | `APP_RAG__SEARCH__FALLBACK_K` | Фрагментов без реранкера (порядок RRF). |
| `rag.search.neighbors` | int | 1 | `APP_RAG__SEARCH__NEIGHBORS` | Соседних чанков с каждой стороны. |
| `rag.search.level_boost` | dict[str, float] | {} | `APP_RAG__SEARCH__LEVEL_BOOST` | Бонус к баллу реранкера по уровню, например personal. |
| `rag.search.rewrite` | bool | true | `APP_RAG__SEARCH__REWRITE` | Переформулировать запрос служебной моделью. |
| `rag.search.rewrite_timeout_s` | float | 5 | `APP_RAG__SEARCH__REWRITE_TIMEOUT_S` | Тайм-аут переформулировки, с. |
| `rag.search.incident_throttle_s` | int | 600 | `APP_RAG__SEARCH__INCIDENT_THROTTLE_S` | Инцидент о пропущенной стадии поиска — не чаще, с. |
| `rag.chunking.target_tokens` | int | 600 | `APP_RAG__CHUNKING__TARGET_TOKENS` | Целевой размер чанка, токенов. |
| `rag.chunking.max_tokens` | int | 800 | `APP_RAG__CHUNKING__MAX_TOKENS` | Жёсткий потолок чанка, токенов. |
| `rag.chunking.min_tokens` | int | 400 | `APP_RAG__CHUNKING__MIN_TOKENS` | Мельче — склеивается с соседом раздела. |
| `rag.chunking.overlap` | float | 0.12 | `APP_RAG__CHUNKING__OVERLAP` | Перекрытие соседних чанков, доля. |
| `rag.context_share` | float | 0.25 | `APP_RAG__CONTEXT_SHARE` | Доля бюджета контекста под фрагменты RAG. |
| `kb.personal_quota.max_documents` | int | 100 | `APP_KB__PERSONAL_QUOTA__MAX_DOCUMENTS` | Документов в личной базе. |
| `kb.personal_quota.max_mb` | int | 500 | `APP_KB__PERSONAL_QUOTA__MAX_MB` | Объём личной базы, МБ. |
| `kb.import_root` | Path | `/srv/import` | `APP_KB__IMPORT_ROOT` | Корень папок для массового импорта; путь импорта не может выйти за него. |
| `exports.ttl_days` | int | 7 | `APP_EXPORTS__TTL_DAYS` | Сколько дней хранится файл выгрузки. |
| `exports.max_messages` | int | 100000 | `APP_EXPORTS__MAX_MESSAGES` | Предел сообщений в одной выгрузке (больше — сузьте фильтр). |
| `security.work_hours.start` | str | `07:00` | `APP_SECURITY__WORK_HOURS__START` | Начало рабочего дня. |
| `security.work_hours.end` | str | `21:00` | `APP_SECURITY__WORK_HOURS__END` | Конец рабочего дня. |
| `security.work_hours.weekdays` | list[int] | [1, 2, 3, 4, 5] | `APP_SECURITY__WORK_HOURS__WEEKDAYS` | Рабочие дни ISO (1 — понедельник). Время — в chat.timezone. |
| `security.subnet_prefix_v4` | int | 24 | `APP_SECURITY__SUBNET_PREFIX_V4` | Подсеть IPv4 для «нового IP». |
| `security.subnet_prefix_v6` | int | 64 | `APP_SECURITY__SUBNET_PREFIX_V6` | Подсеть IPv6 для «нового IP». |
| `security.message_burst.max_messages` | int | 60 | `APP_SECURITY__MESSAGE_BURST__MAX_MESSAGES` | Сколько сообщений за окно — ещё норма. |
| `security.message_burst.window_minutes` | int | 10 | `APP_SECURITY__MESSAGE_BURST__WINDOW_MINUTES` | Окно подсчёта, минут. |
| `security.blocklist_cache_s` | int | 15 | `APP_SECURITY__BLOCKLIST_CACHE_S` | Сколько секунд процесс кэширует список блокировок IP. |
| `retention.deleted_days` | int | 0 | `APP_RETENTION__DELETED_DAYS` | Через сколько дней удалённые чаты стираются физически; 0 — никогда. |
| `monitoring.prometheus_url` | str \| null | null | `APP_MONITORING__PROMETHEUS_URL` | Prometheus с метриками DCGM (GPU); пусто — блок GPU без данных. |
| `monitoring.timeout_s` | float | 2.0 | `APP_MONITORING__TIMEOUT_S` | Тайм-аут запроса к Prometheus, с. |
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
| `models.<роль>.api` | openai \| tei | `openai` | — | Формат API реранкера: openai — vLLM/Jina `POST {base_url}/rerank` (documents → results); tei — text-embeddings-inference `POST /rerank` (texts → список). |
| `models.<роль>.tokenizer` | Path \| null | null | — | Локальный tokenizer.json модели для точного подсчёта токенов (§8.3); без него — оценка по длине текста. |
| `models.<роль>.timeout_s` | float | 600 | — | Тайм-аут запроса к модели, с. |
