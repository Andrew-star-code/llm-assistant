# Тестовый MS SQL дев-стенда (§16.1): SQL Server 2022 Developer с телефонным справочником.
# Только для разработки: лицензия Developer не для прода.
FROM mcr.microsoft.com/mssql/server:2022-CU26-ubuntu-22.04@sha256:ba4c8329f48fb8f02e1416be6a930ebfd71268caee78aa985f3af4315e457c89
COPY --chmod=755 entrypoint.sh /seed/entrypoint.sh
COPY seed.sql /seed/seed.sql
ENV ACCEPT_EULA=Y MSSQL_PID=Developer
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=30 \
    CMD test -f /tmp/seeded && /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT TOP 1 1 FROM corp.dbo.v_phonebook" -b -o /dev/null
ENTRYPOINT ["/seed/entrypoint.sh"]
