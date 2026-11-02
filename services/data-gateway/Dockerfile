# syntax=docker/dockerfile:1.7
# Шлюз данных (§9.5): FastAPI + SQLAlchemy + pyodbc с Microsoft ODBC Driver 18 для MS SQL.
# Контекст сборки — корень репозитория (uv workspace).
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Microsoft ODBC Driver 18 — из репозитория Microsoft (версия закреплена; лицензия — EULA драйвера).
# Ключ репозитория — с проверкой SHA-256. Сеть нужна только при сборке; в рантайме шлюз ходит лишь
# к источникам из каталога.
ARG MSODBCSQL_VERSION=18.5.1.1-1
ADD --checksum=sha256:2fa9c05d591a1582a9aba276272478c262e95ad00acf60eaee1644d93941e3c6 --chmod=644 \
    https://packages.microsoft.com/keys/microsoft.asc /usr/share/keyrings/microsoft-prod.asc
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.asc] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
       msodbcsql18=${MSODBCSQL_VERSION} unixodbc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /srv

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY services/fake-llm/pyproject.toml services/fake-llm/pyproject.toml
COPY services/data-gateway/pyproject.toml services/data-gateway/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package data-gateway --extra mssql --no-install-workspace

COPY services/data-gateway services/data-gateway
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package data-gateway --extra mssql \
    && cp -r services/data-gateway/catalog /srv/catalog

RUN useradd --system --uid 10002 gateway
USER gateway
ENV DG_CATALOG_DIR=/srv/catalog DG_PORT=8090
EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"]

CMD ["python", "-m", "data_gateway"]
