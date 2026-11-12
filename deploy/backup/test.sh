#!/usr/bin/env bash
# Проверка backup.sh без сервера (make test-backup): настоящие PostgreSQL и Qdrant из
# docker-compose.yml в отдельном проекте, бэкап, затем восстановление во временный PostgreSQL.
# Проверяется то же, что в руководстве (раздел 10.2): дамп восстанавливается, данные на месте,
# снапшот Qdrant, архив файлов и конфига существуют, старые бэкапы удаляются.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PROJECT=backup-test
WORK=$(mktemp -d)
export BACKUP_DIR=$WORK/backup
mkdir -p "$BACKUP_DIR/qdrant-snapshots"
chmod -R 777 "$BACKUP_DIR"
cat >"$WORK/.env" <<ENV
POSTGRES_PASSWORD=backup-test-pg
REDIS_PASSWORD=backup-test-redis
QDRANT_API_KEY=backup-test-qdrant
BACKUP_DIR=$BACKUP_DIR
ENV
FILES="-f docker-compose.yml -f ../backup/compose.test.yml"
cd "$ROOT/deploy/compose"
read -r -a FILE_ARGS <<<"$FILES"
DC=(docker compose -p "$PROJECT" --env-file "$WORK/.env" "${FILE_ARGS[@]}")
PG_IMAGE=$("${DC[@]}" config --images | grep -m1 '^postgres:')

cleanup() {
  docker rm -f backup-test-restore backup-test-qdrant >/dev/null 2>&1 || true
  "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  docker run --rm -v "$WORK":/w --entrypoint sh "$PG_IMAGE" -c 'rm -rf /w/backup' || true
  rm -rf "$WORK"
}
trap cleanup EXIT

"${DC[@]}" up -d --wait postgres qdrant api >/dev/null

# Данные: строка в PostgreSQL, коллекция с точкой в Qdrant, файл в томе хранилища.
"${DC[@]}" exec -T postgres psql -U assistant -d assistant -qc \
  "create table backup_probe(id int primary key, note text); insert into backup_probe values (1, 'проверка')"
"${DC[@]}" exec -T -u root api sh -c 'mkdir -p /srv/storage/kb && echo документ > /srv/storage/kb/doc.txt'
"${DC[@]}" exec -T api python -c "
import json, os, urllib.request
def call(method, path, body):
    req = urllib.request.Request('http://qdrant:6333' + path, method=method,
        data=json.dumps(body).encode(),
        headers={'api-key': os.environ['APP_QDRANT_API_KEY'], 'content-type': 'application/json'})
    urllib.request.urlopen(req, timeout=30).read()
call('PUT', '/collections/probe', {'vectors': {'size': 2, 'distance': 'Cosine'}})
call('PUT', '/collections/probe/points?wait=true', {'points': [{'id': 1, 'vector': [0.1, 0.9]}]})"

# Старый бэкап — должен быть удалён по сроку хранения.
mkdir -p "$BACKUP_DIR/2020-01-01"
touch -d '40 days ago' "$BACKUP_DIR/2020-01-01"

APP_DIR=$ROOT ENV_FILE=$WORK/.env COMPOSE_PROJECT_NAME=$PROJECT COMPOSE_FILES=$FILES \
  "$ROOT/deploy/backup/backup.sh"

DEST=$BACKUP_DIR/$(date +%F)
fail() { echo "test-backup: $1" >&2; exit 1; }
[ -s "$DEST/postgres.dump" ] || fail "нет дампа PostgreSQL"
[ -s "$BACKUP_DIR/qdrant-snapshots/$(cat "$DEST/qdrant-snapshot.txt")" ] || fail "нет снапшота Qdrant"
tar -tf "$DEST/storage.tar" | grep -q 'kb/doc.txt' || fail "в архиве файлов нет kb/doc.txt"
tar -tf "$DEST/config.tar" | grep -q '^config/app.yaml$' || fail "в архиве конфига нет app.yaml"
[ ! -e "$BACKUP_DIR/2020-01-01" ] || fail "старый бэкап не удалён"

# Восстановление во временный контейнер, как в руководстве (10.2).
docker run -d --name backup-test-restore -e POSTGRES_PASSWORD=restore "$PG_IMAGE" >/dev/null
for _ in $(seq 30); do
  docker exec backup-test-restore pg_isready -U postgres -q && break
  sleep 1
done
sleep 2 # первый запуск: сервер перезапускается после инициализации
docker exec -i backup-test-restore pg_restore -U postgres -d postgres --create --no-owner \
  --no-acl <"$DEST/postgres.dump"
NOTE=$(docker exec backup-test-restore psql -U postgres -d assistant -Atc \
  'select note from backup_probe where id = 1')
[ "$NOTE" = "проверка" ] || fail "после восстановления данных нет: «$NOTE»"

# Qdrant: новый пустой экземпляр, запущенный с полным снапшотом (runbooks/backup-restore.md).
QDRANT_IMAGE=$("${DC[@]}" config --images | grep -m1 '^qdrant/')
SNAPSHOT=$(cat "$DEST/qdrant-snapshot.txt")
docker run -d --name backup-test-qdrant -v "$BACKUP_DIR/qdrant-snapshots":/snapshots:ro \
  "$QDRANT_IMAGE" ./qdrant --storage-snapshot "/snapshots/$SNAPSHOT" >/dev/null
POINTS=""
for _ in $(seq 30); do
  POINTS=$(docker exec backup-test-qdrant bash -c \
    'exec 3<>/dev/tcp/127.0.0.1/6333 && printf "GET /collections/probe HTTP/1.0\r\n\r\n" >&3 && cat <&3' \
    2>/dev/null | grep -o '"points_count":[0-9]*' || true)
  [ -n "$POINTS" ] && break
  sleep 1
done
[ "$POINTS" = '"points_count":1' ] || fail "Qdrant после восстановления: «$POINTS» вместо одной точки"

echo "test-backup: бэкап снят; PostgreSQL и Qdrant восстановлены, архивы файлов и конфига на месте"
