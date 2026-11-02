# syntax=docker/dockerfile:1.7
# Образы api (цель api) и воркера файлов (цель worker: тот же код + LibreOffice, Tesseract, шрифты).
# Контекст сборки — корень репозитория: нужны uv.lock workspace и каталог config/.
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    OTEL_SDK_DISABLED=true \
    APP_CONFIG_DIR=/srv/config

# uv — из PyPI с закреплённой версией: тот же источник, что у остальных зависимостей.
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /srv

# Сначала только зависимости — слой кэшируется, пока не меняется uv.lock.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY services/fake-llm/pyproject.toml services/fake-llm/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ai-assistant-api --no-install-workspace

COPY backend backend
COPY config config
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ai-assistant-api

# Том с файлами (фото из AD, загрузки): каталог создаётся с владельцем app — именованный том
# Docker при первом монтировании наследует эти права.
RUN useradd --system --uid 10001 --home-dir /srv app \
 && mkdir -p /srv/storage && chown app /srv/storage
USER app
WORKDIR /srv/backend
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Открытые SSE не дают uvicorn завершиться сами: через 5 с соединения закрываются, и lifespan
# успевает сохранить идущие ответы как «прерванные» до SIGKILL Docker (stop_grace_period).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "5"]


# ---------------------------------------------------------------- воркер файлов (§4, §9.3–9.4)
# Разбор вложений (LibreOffice для DOC/RTF/ODT/XLS/PPT, OCR сканов) и генерация DOCX/PDF/XLSX/PPTX.
# pandoc — в колесе pypandoc-binary. Шрифты: метрически совместимые с Calibri/Cambria/Times/Arial,
# иначе PDF и превью «поплывут».
FROM api AS worker
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
      tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
      fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
 && rm -rf /var/lib/apt/lists/*
USER app
HEALTHCHECK NONE
CMD ["celery", "-A", "app.workers.celery_app", "worker", "-Q", "files", "-c", "2", "--without-gossip", "--without-mingle", "-n", "files@%h"]
