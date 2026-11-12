#!/usr/bin/env bash
# Проверка шаблона nginx без сервера (make test-nginx): образ и подстановка PORTAL_HOST — те же,
# что в compose.prod.yml; сертификат — временный самоподписанный, адреса api и frontend —
# заглушки (nginx -t требует, чтобы имена разрешались).
set -euo pipefail
cd "$(dirname "$0")"
IMAGE=$(grep -o 'nginx:[^ ]*@sha256:[0-9a-f]*' ../compose/compose.prod.yml | head -1)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=ai.test.local" \
  -keyout "$TMP/tls_privkey.pem" -out "$TMP/tls_fullchain.pem" 2>/dev/null
chmod 755 "$TMP" && chmod 644 "$TMP"/*.pem
# Штатный entrypoint образа подставляет шаблон только для команды nginx; -T проверяет
# конфигурацию и печатает её целиком.
CONF=$(docker run --rm -e PORTAL_HOST=ai.test.local \
  --add-host api:127.0.0.1 --add-host frontend:127.0.0.1 \
  -v "$PWD/templates":/etc/nginx/templates:ro -v "$TMP":/run/secrets:ro \
  "$IMAGE" nginx -T 2>&1) || { echo "$CONF" >&2; exit 1; }
# shellcheck disable=SC2016  # $host — переменная nginx, а не оболочки
for expected in 'server_name ai.test.local;' 'proxy_set_header Host $host;' \
  'proxy_buffering off;' 'proxy_pass http://api:8000;'; do
  grep -qF "$expected" <<<"$CONF" || { echo "nginx: в конфигурации нет «$expected»" >&2; exit 1; }
done
echo "nginx: конфигурация корректна, PORTAL_HOST подставлен, переменные nginx не затронуты"
