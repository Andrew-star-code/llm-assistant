"""Запуск: ``python -m fake_llm`` (порт — FAKE_LLM_PORT, по умолчанию 8080)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "fake_llm.app:create_app",
        factory=True,
        host=os.environ.get("FAKE_LLM_HOST", "0.0.0.0"),  # noqa: S104 — сервис внутри Docker-сети
        port=int(os.environ.get("FAKE_LLM_PORT", "8080")),
        log_level=os.environ.get("FAKE_LLM_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
