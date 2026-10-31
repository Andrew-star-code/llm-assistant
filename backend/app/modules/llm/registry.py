"""Реестр моделей по ролям (§8.2): код обращается к ролям (`chat`, `utility`, …), а не к именам.

Смена модели — правка ``config/models.yaml`` без изменений кода (``docs/guides/add-model.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.core.config import ModelEndpoint, Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class RequestPlan:
    """Что именно уйдёт в модель: роль, эндпоинт и параметры запроса."""

    role: str
    endpoint: ModelEndpoint
    params: dict[str, Any]
    thinking: bool


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.models = settings.models
        self._clients: dict[str, AsyncOpenAI] = {}

    def get(self, role: str) -> ModelEndpoint:
        try:
            return self.models[role]
        except KeyError:
            raise AppError(f"Модель с ролью {role!r} не описана", code="unknown_model") from None

    def client(self, role: str) -> AsyncOpenAI:
        if role not in self._clients:
            endpoint = self.get(role)
            api_key = endpoint.api_key.get_secret_value() if endpoint.api_key else "not-needed"
            self._clients[role] = AsyncOpenAI(
                base_url=endpoint.base_url,
                api_key=api_key,
                max_retries=0,  # повтор решает пользователь кнопкой «Повторить» (§7.4)
                timeout=endpoint.timeout_s,
            )
        return self._clients[role]

    def thinking_available(self, role: str) -> bool:
        return self.get(role).thinking.mode != "none"

    def plan(self, role: str, *, thinking: bool | None) -> RequestPlan:
        """Параметры запроса с учётом режима thinking (§8.2) и сэмплинга из карточки модели."""
        endpoint = self.get(role)
        mode = endpoint.thinking.mode
        enabled = endpoint.thinking.default if thinking is None else thinking
        enabled = enabled and mode != "none"

        if mode == "separate_model" and enabled and endpoint.thinking.model_role:
            # Запросы с размышлениями уходят на отдельную модель из реестра.
            target_role = endpoint.thinking.model_role
            target = self.get(target_role)
            return RequestPlan(target_role, target, _sampling(target, thinking=True), True)

        params = _sampling(endpoint, thinking=enabled)
        extra: dict[str, Any] = params.setdefault("extra_body", {})
        if mode == "chat_template_kwarg":
            extra["chat_template_kwargs"] = {endpoint.thinking.kwarg: enabled}
        elif mode == "reasoning_effort" and enabled:
            params["reasoning_effort"] = endpoint.thinking.effort or "medium"
        if not extra:
            params.pop("extra_body")
        return RequestPlan(role, endpoint, params, enabled)

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()


def _sampling(endpoint: ModelEndpoint, *, thinking: bool) -> dict[str, Any]:
    """Стандартные параметры OpenAI — полями запроса, расширения vLLM — в ``extra_body``."""
    source = endpoint.sampling.thinking if thinking else endpoint.sampling.default
    values = source.model_dump(exclude_none=True)
    params: dict[str, Any] = {"model": endpoint.model}
    for key in ("temperature", "top_p", "presence_penalty"):
        if key in values:
            params[key] = values.pop(key)
    if endpoint.max_output_tokens:
        params["max_tokens"] = endpoint.max_output_tokens
    if values:  # top_k, min_p, repetition_penalty
        params["extra_body"] = values
    return params
