# syntax=docker/dockerfile:1.7
# mock-AD для разработки: Samba AD DC с тестовыми пользователями (§6.7 SPEC). Не для прода.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      samba samba-ad-dc samba-ad-provision samba-dsdb-modules samba-vfs-modules \
      winbind ldb-tools ldap-utils openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/mock-ad-entrypoint
COPY seed /seed
RUN chmod +x /usr/local/bin/mock-ad-entrypoint /seed/seed.sh

EXPOSE 389 636
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD ldapsearch -LLL -x -H ldap://127.0.0.1 -b "" -s base defaultNamingContext >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/mock-ad-entrypoint"]
