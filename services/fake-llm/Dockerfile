# syntax=docker/dockerfile:1.7
# Контекст сборки — корень репозитория (uv workspace).
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# uv — из PyPI с закреплённой версией: тот же источник, что у остальных зависимостей.
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /srv

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY services/fake-llm/pyproject.toml services/fake-llm/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package fake-llm --no-install-workspace

COPY services/fake-llm services/fake-llm
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package fake-llm

RUN useradd --system --uid 10001 fakellm
USER fakellm
EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["python", "-m", "fake_llm"]
