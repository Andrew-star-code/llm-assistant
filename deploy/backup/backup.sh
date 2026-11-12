#!/usr/bin/env bash
# Ночной бэкап (docs/runbooks/first-deploy.md, раздел 10): PostgreSQL, Qdrant, файлы, конфиг.
#
#   /srv/ai-assistant/deploy/backup/backup.sh
#
# Секреты (.env, /srv/ai-assistant-secrets) сюда не входят — их бэкапят отдельно, в защищённое
# хранилище. Проверка скрипта без сервера: make test-backup.
#
# Переменные (значения по умолчанию — для сервера из руководства):
#   APP_DIR        каталог репозитория                         /srv/ai-assistant
#   BACKUP_DIR     куда писать (тот же, что в compose.prod.yml) /backup/ai-assistant
#   KEEP_DAYS      сколько дней хранить                        30
#   COMPOSE_FILES  файлы compose                               -f docker-compose.yml -f compose.prod.yml
#   COMPOSE_PROJECT_NAME  имя проекта compose                  ai-assistant
set -euo pipefail

APP_DIR=${APP_DIR:-/srv/ai-assistant}
cd "$APP_DIR/deploy/compose"
ENV_FILE=${ENV_FILE:-.env}
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
BACKUP_DIR=${BACKUP_DIR:-/backup/ai-assistant}
KEEP_DAYS=${KEEP_DAYS:-30}
PROJECT=${COMPOSE_PROJECT_NAME:-ai-assistant}
read -r -a FILES <<<"${COMPOSE_FILES:--f docker-compose.yml -f compose.prod.yml}"
DC=(docker compose -p "$PROJECT" --env-file "$ENV_FILE" "${FILES[@]}")

DEST=$BACKUP_DIR/$(date +%F)
mkdir -p "$DEST" "$BACKUP_DIR/qdrant-snapshots"

# PostgreSQL — логический дамп в формате custom. Пишем во временный файл: оборванный дамп не
# должен выглядеть как готовый.
"${DC[@]}" exec -T postgres pg_dump -U "${POSTGRES_USER:-assistant}" -Fc \
  "${POSTGRES_DB:-assistant}" >"$DEST/postgres.dump.part"
[ -s "$DEST/postgres.dump.part" ] || { echo "backup: пустой дамп PostgreSQL" >&2; exit 1; }
mv "$DEST/postgres.dump.part" "$DEST/postgres.dump"

# Qdrant — полный снапшот; файл появляется в $BACKUP_DIR/qdrant-snapshots (том из
# compose.prod.yml). Запрос — из контейнера api: у Qdrant порт наружу не опубликован.
SNAPSHOT=$("${DC[@]}" exec -T api python -c "
import json, os, urllib.request
req = urllib.request.Request('http://qdrant:6333/snapshots', method='POST',
                             headers={'api-key': os.environ['APP_QDRANT_API_KEY']})
print(json.load(urllib.request.urlopen(req, timeout=3600))['result']['name'])")
[ -s "$BACKUP_DIR/qdrant-snapshots/$SNAPSHOT" ] || {
  echo "backup: снапшот Qdrant $SNAPSHOT не появился в $BACKUP_DIR/qdrant-snapshots" >&2
  exit 1
}
echo "$SNAPSHOT" >"$DEST/qdrant-snapshot.txt"

# Файлы пользователей и баз знаний — копия тома. Образ — уже имеющийся на сервере (redis на
# alpine): после отключения интернета новые образы взять неоткуда.
TOOLS_IMAGE=$("${DC[@]}" config --images | grep -m1 '^redis:')
docker run --rm -v "${PROJECT}_api-storage":/src:ro -v "$DEST":/dst --entrypoint tar \
  "$TOOLS_IMAGE" -C /src -cf /dst/storage.tar .

# Конфиг (без секретов) — чтобы восстановить ту же версию поведения.
tar -C "$APP_DIR" -cf "$DEST/config.tar" config

# Хранить KEEP_DAYS дней.
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" \
  -exec rm -rf {} +
find "$BACKUP_DIR/qdrant-snapshots" -type f -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $DEST"
