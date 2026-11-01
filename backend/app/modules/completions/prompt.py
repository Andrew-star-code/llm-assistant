"""Сборка промпта (§8.1) и бюджет контекста (§8.3).

Системный промпт: базовые правила → пользователь (§11.1) → ★ память → сценарий (этап 5) →
контекст RAG (этап 4) → вложения (этап 3). Затем — история активной ветки и новое сообщение.

Бюджет: ``context_length`` минус резерв на ответ. При переполнении усекается старая история.
TODO(stage-4): затем сокращать фрагменты RAG; TODO(stage-3): вложения → «оглавление + инструменты».
SHOULD: краткое саммари усечённой истории служебной моделью.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.config import ModelEndpoint, Settings
from app.core.errors import AppError
from app.modules.llm.tokens import TokenCounter

DEFAULT_CONTEXT = 32768
DEFAULT_RESERVE = 4096

ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class PromptUser:
    full_name: str
    title: str | None
    department: str | None
    address: str | None


@dataclass(frozen=True)
class Turn:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class BuiltPrompt:
    messages: list[dict[str, Any]]
    prompt_tokens: int
    history_total: int
    history_used: int
    exact_tokens: bool

    def trace(self) -> dict[str, Any]:
        return {
            "prompt_tokens_estimate": self.prompt_tokens,
            "history_turns_total": self.history_total,
            "history_turns_used": self.history_used,
            "tokens_exact": self.exact_tokens,
        }


class PromptRenderer:
    """Рендер Jinja2-шаблонов из ``config/prompts``."""

    def __init__(self, prompts_dir: Path) -> None:
        self.env = Environment(
            loader=FileSystemLoader(prompts_dir),
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701 — это текст для модели, не HTML
            keep_trailing_newline=False,
        )

    def render(self, name: str, **context: Any) -> str:
        return self.env.get_template(name).render(**context).strip()


def format_now(now: datetime, timezone: str) -> str:
    local = now.astimezone(ZoneInfo(timezone))
    return local.strftime("%d.%m.%Y %H:%M")


def system_prompt(
    renderer: PromptRenderer,
    settings: Settings,
    user: PromptUser,
    now: datetime,
    *,
    base_template: str | None = None,
    moderation: dict[str, Any] | None = None,
) -> str:
    """Базовые правила + пользователь. ``base_template`` — шаблон из админки «Настройки» вместо
    ``system/base.md.j2``: шаблон админа рендерится только в песочнице Jinja2."""
    context = {
        "company": settings.chat.company_name,
        "now": format_now(now, settings.chat.timezone),
        "timezone": settings.chat.timezone,
    }
    if base_template:
        from app.modules.scenarios.service import render_admin_template

        # Шаблон с ошибкой не оставляет модель без базовых правил — тогда берётся файл.
        base = render_admin_template(base_template, context) or renderer.render(
            "system/base.md.j2", **context
        )
    else:
        base = renderer.render("system/base.md.j2", **context)
    parts = [base, renderer.render("system/user.md.j2", user=user)]
    if moderation is not None:
        # Отдельным шаблоном: базовый промпт из админки не может убрать правила модерации.
        parts.append(renderer.render("system/moderation.md.j2", **moderation))
    return "\n\n".join(p for p in parts if p)


def build_messages(
    *,
    system: str,
    history: list[Turn],
    message: str,
    endpoint: ModelEndpoint,
    counter: TokenCounter,
) -> BuiltPrompt:
    """Система + максимум свежей истории, влезающей в бюджет + новое сообщение."""
    context = endpoint.context_length or DEFAULT_CONTEXT
    reserve = endpoint.max_output_tokens or DEFAULT_RESERVE
    budget = context - reserve

    head = [{"role": "system", "content": system}]
    tail = [{"role": "user", "content": message}]
    used = counter.count_messages(head) + counter.count_messages(tail)
    if used > budget:
        raise AppError(
            "Сообщение слишком длинное для контекста модели",
            code="message_too_long",
            status_code=413,
        )

    kept: list[dict[str, Any]] = []
    for turn in reversed(history):
        item = {"role": turn.role, "content": turn.content}
        cost = counter.count_messages([item])
        if used + cost > budget:
            break
        kept.append(item)
        used += cost
    kept.reverse()
    # История должна начинаться с сообщения пользователя: обрезанный «хвост» ответа без вопроса
    # сбивает модель.
    while kept and kept[0]["role"] != "user":
        used -= counter.count_messages([kept.pop(0)])
    return BuiltPrompt(
        messages=[*head, *kept, *tail],
        prompt_tokens=used,
        history_total=len(history),
        history_used=len(kept),
        exact_tokens=counter.exact,
    )
