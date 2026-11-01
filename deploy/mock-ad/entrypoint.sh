#!/usr/bin/env bash
# Первый запуск: провижн домена, свой CA и сертификат для LDAPS, тестовые данные.
# Повторные запуски: данные берутся из томов /var/lib/samba и /etc/samba.
set -euo pipefail

REALM="${MOCK_AD_REALM:-CORP.LOCAL}"
DOMAIN="${MOCK_AD_DOMAIN:-CORP}"
ADMIN_PASSWORD="${MOCK_AD_ADMIN_PASSWORD:?задайте MOCK_AD_ADMIN_PASSWORD}"
FQDN="$(hostname -f)"
TLS_DIR=/var/lib/samba/private/tls-mock
EXPORT_DIR="${MOCK_AD_EXPORT_DIR:-/export}"

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
  echo "mock-ad: провижн домена ${REALM} (хост ${FQDN})"
  rm -f /etc/samba/smb.conf
  samba-tool domain provision \
    --realm="${REALM}" --domain="${DOMAIN}" --server-role=dc \
    --dns-backend=SAMBA_INTERNAL --adminpass="${ADMIN_PASSWORD}" \
    --option="dns forwarder = 127.0.0.11" \
    --option="ldap server require strong auth = allow_sasl_over_tls"

  echo "mock-ad: выпуск CA и сертификата LDAPS для ${FQDN}"
  mkdir -p "${TLS_DIR}"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=Mock Corp CA" \
    -keyout "${TLS_DIR}/ca.key" -out "${TLS_DIR}/ca.pem" 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -subj "/CN=${FQDN}" \
    -keyout "${TLS_DIR}/key.pem" -out "${TLS_DIR}/req.csr" 2>/dev/null
  printf "subjectAltName=DNS:%s,DNS:%s,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n" \
    "${FQDN}" "$(hostname -s)" > "${TLS_DIR}/ext.cnf"
  openssl x509 -req -in "${TLS_DIR}/req.csr" -CA "${TLS_DIR}/ca.pem" -CAkey "${TLS_DIR}/ca.key" \
    -CAcreateserial -days 3650 -extfile "${TLS_DIR}/ext.cnf" -out "${TLS_DIR}/cert.pem" 2>/dev/null
  chmod 600 "${TLS_DIR}/key.pem" "${TLS_DIR}/ca.key"
  sed -i "/\[global\]/a \\
\ttls enabled = yes\\
\ttls keyfile = ${TLS_DIR}/key.pem\\
\ttls certfile = ${TLS_DIR}/cert.pem\\
\ttls cafile = ${TLS_DIR}/ca.pem" /etc/samba/smb.conf

  /seed/seed.sh
fi

mkdir -p "${EXPORT_DIR}"
cp "${TLS_DIR}/ca.pem" "${EXPORT_DIR}/ca.pem"
chmod 644 "${EXPORT_DIR}/ca.pem"

echo "mock-ad: запуск samba"
exec samba --foreground --no-process-group --debug-stdout
