"""Сборка промпта (§8.1) и бюджет контекста (§8.3).

Системный промпт: базовые правила → пользователь (§11.1) → ★ память → сценарий (этап 5) →
контекст RAG (этап 4) → вложения (этап 3). Затем — история активной ветки и новое сообщение.

Бюджет: ``context_length`` минус резерв на ответ и описания инструментов. При переполнении
усекается старая история — целыми ходами: ответ ассистента уходит вместе со своими вызовами
инструментов. Фрагменты RAG ограничены ``rag.context_share`` (``generation._auto_rag``), вложения —
``files.full_text_budget_share`` (``attachments.py``); в цикле инструментов бюджет держит
``context.LoopContext``.
TODO(context-summary): краткое саммари усечённой истории служебной моделью (SHOULD §8.3) —
отложено, план в ``docs/status.md`` («Отложенные задачи»).
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
class ToolStep:
    """Вызов инструмента из прошлого ответа: модель видит, что уже запрашивала и что получила."""

    iteration: int
    call_id: str
    name: str
    arguments: str  # JSON, как его отдала модель
    result: str


@dataclass(frozen=True)
class Turn:
    role: ChatRole
    content: str
    steps: tuple[ToolStep, ...] = ()

    def messages(self) -> list[dict[str, Any]]:
        """Ход в формате API: шаги инструментов по итерациям, затем сам текст."""
        items: list[dict[str, Any]] = []
        for iteration in sorted({s.iteration for s in self.steps}):
            group = [s for s in self.steps if s.iteration == iteration]
            items.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": s.call_id,
                            "type": "function",
                            "function": {"name": s.name, "arguments": s.arguments},
                        }
                        for s in group
                    ],
                }
            )
            items.extend(
                {"role": "tool", "tool_call_id": s.call_id, "content": s.result} for s in group
            )
        items.append({"role": self.role, "content": self.content})
        return items


@dataclass(frozen=True)
class BuiltPrompt:
    messages: list[dict[str, Any]]
    prompt_tokens: int
    history_total: int
    history_used: int
    exact_tokens: bool
    budget: int = 0  # сколько токенов промпта допустимо всего (вместе с описаниями инструментов)
    overhead: int = 0  # описания инструментов: в ``messages`` их нет, а место занимают
    costs: tuple[int, ...] = ()  # цена каждого сообщения — чтобы цикл инструментов не пересчитывал
    history_messages: int = 0  # сообщений истории между системным промптом и вопросом

    def trace(self) -> dict[str, Any]:
        return {
            "prompt_tokens_estimate": self.prompt_tokens,
            "history_turns_total": self.history_total,
            "history_turns_used": self.history_used,
            "history_tool_steps": sum(
                len(m["tool_calls"]) for m in self.messages if m.get("tool_calls")
            ),
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
    overhead: int = 0,
    history_reserve: int = 0,
) -> BuiltPrompt:
    """Система + максимум свежей истории, влезающей в бюджет + новое сообщение.

    ``overhead`` — токены вне сообщений (описания инструментов). ``history_reserve`` — место,
    которое история оставляет под результаты инструментов этого ответа: без него длинный чат
    заполняет контекст до предела, и первый же вызов инструмента его переполняет.
    """
    context = endpoint.context_length or DEFAULT_CONTEXT
    reserve = endpoint.max_output_tokens or DEFAULT_RESERVE
    budget = context - reserve

    head = [{"role": "system", "content": system}]
    tail = [{"role": "user", "content": message}]
    head_cost, tail_cost = counter.count_messages(head), counter.count_messages(tail)
    used = overhead + head_cost + tail_cost
    if used > budget:
        raise AppError(
            "Сообщение слишком длинное для контекста модели",
            code="message_too_long",
            status_code=413,
        )

    kept: list[tuple[Turn, list[dict[str, Any]], list[int]]] = []
    for turn in reversed(history):
        items = turn.messages()
        costs = [counter.count_messages([item]) for item in items]
        if used + sum(costs) > budget - history_reserve:
            break
        kept.append((turn, items, costs))
        used += sum(costs)
    kept.reverse()
    # История должна начинаться с сообщения пользователя: обрезанный «хвост» ответа без вопроса
    # сбивает модель.
    while kept and kept[0][0].role != "user":
        used -= sum(kept.pop(0)[2])
    middle = [item for _, items, _ in kept for item in items]
    return BuiltPrompt(
        messages=[*head, *middle, *tail],
        prompt_tokens=used,
        history_total=len(history),
        history_used=len(kept),
        exact_tokens=counter.exact,
        budget=budget,
        overhead=overhead,
        costs=(head_cost, *(c for _, _, costs in kept for c in costs), tail_cost),
        history_messages=len(middle),
    )
