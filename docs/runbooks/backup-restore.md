# Восстановление из бэкапа

Что делать, если данные потеряны или испорчены: диск, ошибочное удаление, неудачное обновление с
миграциями. Бэкап снимает `deploy/backup/backup.sh` каждую ночь
([первый запуск, раздел 10](first-deploy.md#10-шаг-7-бэкапы-и-проверка-восстановления)).

**Что проверено.** Шаги «PostgreSQL» и «Qdrant» в чистые контейнеры проверяет `make test-backup`
на настоящих образах. Восстановление **поверх работающего прода** (остановка сервисов, тома) без
сервера не проверялось — пройдите этот документ на генеральной репетиции и запишите время в
`docs/status.md`.

## Что лежит в бэкапе

```text
/backup/ai-assistant/<дата>/
  postgres.dump          пользователи, чаты, сообщения, базы знаний (метаданные), аудит, лимиты
  qdrant-snapshot.txt    имя снапшота Qdrant за эту дату
  storage.tar            файлы: вложения, документы баз знаний, сгенерированные файлы, фото
  config.tar             конфиг без секретов
/backup/ai-assistant/qdrant-snapshots/<имя>.snapshot   векторы поиска
```

Секретов в бэкапе нет: `deploy/compose/.env` и `/srv/ai-assistant-secrets` хранятся отдельно. Без
`.env` придётся заново выпустить внутренние пароли (раздел 5.2 первого запуска) — данные при этом
восстановятся.

Потеря данных — до суток (ночной бэкап). Redis не бэкапится: в нём сессии и счётчики лимитов —
после восстановления пользователи входят заново, расход лимитов текущего окна начинается с нуля.

## Порядок

Все команды — из `/srv/ai-assistant/deploy/compose`; `DC` — сокращение:

```bash
cd /srv/ai-assistant/deploy/compose
DC="docker compose -f docker-compose.yml -f compose.prod.yml"
DAY=<дата бэкапа, например 2026-11-12>
```

### 1. Остановить приложение

Модели и nginx можно не трогать. Пользователи увидят ошибку подключения.

```bash
$DC stop nginx api generator worker worker-kb scheduler
```

### 2. PostgreSQL

Данные трёх хранилищ должны быть за **одну дату**: чаты ссылаются на файлы, документы баз — на
векторы.

```bash
$DC exec -T postgres psql -U assistant -d postgres -c 'DROP DATABASE IF EXISTS assistant WITH (FORCE)'
```

```bash
$DC exec -T postgres pg_restore -U assistant -d postgres --create --no-owner --no-acl < /backup/ai-assistant/$DAY/postgres.dump
```

```bash
$DC exec -T postgres psql -U assistant -d assistant -c 'select count(*) from users; select count(*) from chats;'
```

Если версия кода новее дампа — после восстановления примените миграции: `$DC run --rm migrate`.

### 3. Qdrant

Qdrant восстанавливается запуском с полным снапшотом в **пустое** хранилище.

```bash
$DC rm -sf qdrant
```

```bash
docker volume rm ai-assistant_qdrant-data
```

```bash
$DC run -d --name qdrant-restore --no-deps qdrant ./qdrant --storage-snapshot /qdrant/snapshots/$(cat /backup/ai-assistant/$DAY/qdrant-snapshot.txt)
```

Дождитесь в логах `docker logs -f qdrant-restore` строки о запуске HTTP-сервера (снапшот
распакован), затем остановите временный контейнер и поднимите сервис штатно:

```bash
docker rm -f qdrant-restore
```

```bash
$DC up -d qdrant
```

Если векторы потеряны, а бэкапа Qdrant нет — их можно построить заново из документов:
админка → «Базы знаний» → «Переиндексировать» (нужны PostgreSQL и файлы; время — как у
первичного импорта).

### 4. Файлы

Образ для распаковки — тот же, что использует `backup.sh` (redis на alpine), он уже есть на сервере.

```bash
docker run --rm -v ai-assistant_api-storage:/dst -v /backup/ai-assistant/$DAY:/src:ro --entrypoint sh $($DC config --images | grep -m1 '^redis:') -c 'rm -rf /dst/* && tar -C /dst -xf /src/storage.tar'
```

### 5. Конфиг

Только если он тоже потерян или испорчен: `config.tar` распаковывается в `/srv/ai-assistant`.

```bash
tar -C /srv/ai-assistant -xf /backup/ai-assistant/$DAY/config.tar
```

### 6. Запустить и проверить

```bash
$DC up -d
```

```bash
uv run python scripts/smoke.py --base-url https://<портал> --provider ldap --login <сотрудник> --admin <админ> --ask-password
```

Вручную: открыть старый чат с вложением и скачать файл; задать вопрос по базе знаний — ответ с
цитатами, клик открывает документ. В админке «Инциденты» — без новых записей.

## Частичные случаи

- **Удалили чат или документ по ошибке.** Чаты удаляются мягко и физически стираются после срока
  хранения (`retention`), документы баз — сразу. Точечно: восстановите дамп во **временный**
  PostgreSQL ([раздел 10.2](first-deploy.md#102-проверка-восстановления-до-пуска-пользователей))
  и перенесите нужные строки; для документа проще загрузить его заново.
- **Неудачное обновление с миграциями.** Откат кода схему не откатывает: шаги 1, 2 и 6 с
  бэкапом, снятым перед обновлением (раздел 13.1 первого запуска), и прежней `APP_VERSION`.
- **Потерян только Qdrant.** Шаг 3 или переиндексация из админки.
