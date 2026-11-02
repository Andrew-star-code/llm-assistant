#!/bin/bash
# Запускает SQL Server, ждёт готовности и применяет seed.sql (идемпотентно).
set -euo pipefail
/opt/mssql/bin/sqlservr &
server=$!
sqlcmd=/opt/mssql-tools18/bin/sqlcmd
for _ in $(seq 1 90); do
  if "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" -b >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
# После перезапуска master отвечает раньше, чем восстановлена corp (Msg 904) — seed повторяем.
for attempt in $(seq 1 30); do
  "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -b -i /seed/seed.sql \
    -v READER_PASSWORD="$MSSQL_READER_PASSWORD" && break
  [ "$attempt" -lt 30 ] || exit 1
  sleep 2
done
touch /tmp/seeded
wait "$server"
