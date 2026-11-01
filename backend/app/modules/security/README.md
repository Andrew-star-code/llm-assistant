# modules/security

> Статус: журнал входов и защита от перебора — этап 1; правила подозрительности, блокировки IP,
> доверенные подсети и инциденты — этап 7 (§13.4).

**Назначение:** журнал входов, защита от перебора паролей, блокировки.

**Публичный интерфейс:**

* `service.record_login_event` — запись в `login_events`: время, логин, IP, User-Agent, способ,
  результат, точная причина отказа (`failure_reason`), флаги риска.
* `bruteforce.BruteforceGuard` — счётчики неудач в Redis по логину (5 за 15 минут → блокировка
  логина на 15 минут) и по IP (20 за 15 минут → на 60 минут). Порог по логину ниже политики
  блокировки AD, чтобы перебор через портал не блокировал доменные учётки (§6.2).
  Разблокировка пользователя в админке снимает и блокировку логина.
* `rules` — правила подозрительности (§13.4): флаги событий входа `after_failures`,
  `new_subnet`, `off_hours`, `concurrent_subnets`, `blocked_attempt`; 20 неудач с IP —
  блокировка IP на `per_ip.lock_minutes` (`ip_blocks`, `source = auto`) и инцидент `security`
  со списком перебиравшихся логинов (доверенная подсеть — только инцидент); больше
  `security.message_burst.max_messages` сообщений за окно — инцидент `security` (один на окно).
  Пороги и рабочее время — `security.*` и `auth.bruteforce.*` в конфиге.
* `ipblocks.Blocklist` — активные блокировки и доверенные подсети в памяти процесса; изменение
  повышает версию в Redis, и все процессы перечитывают таблицы на следующем запросе.
  Заблокированный адрес не входит и не работает с API даже с открытой сессией (403 `ip_blocked`).
* `GET /api/admin/logins` (фильтры `flagged`, `unreviewed`, `ip`), `POST …/logins/{id}/review`,
  `GET/POST/DELETE /api/admin/ip-blocks`, `GET/POST/DELETE /api/admin/trusted-networks` —
  `admin/security_router.py` (просмотр — `admin.logins.view`, изменения — `admin.security.manage`,
  аудит). Подсети шире /16 (IPv6 — /48) и свой адрес заблокировать нельзя.

Отказы `locked_*` и `ad_unavailable` счётчики не увеличивают.

**Зависит от:** Redis.

**Точки расширения:** новое правило — функция в `rules.py` и флаг в `FLAG_LEVELS` (подпись — в
i18n `admin.logins.flags.*`).

**Данные:** `login_events` (+ `reviewed_by`, `reviewed_at`), `ip_blocks`, `trusted_networks`;
Redis `bf:fail:*`, `bf:lock:*`, `security:burst:*`, `security:blocklist:version`.

**Тесты:** `backend/tests/integration/test_auth_ldap.py::test_sixth_failed_attempt_locks_login`,
`backend/tests/integration/test_security.py`.
