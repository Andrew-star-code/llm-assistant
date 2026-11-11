"""Бюджет контекста в цикле инструментов (§8.3, §8.4).

``build_messages`` укладывает в бюджет первый запрос. Дальше каждая итерация дописывает вызовы
модели и результаты инструментов, и без контроля промпт перерастает ``context_length`` — модель
отвечает ошибкой вместо ответа. ``LoopContext`` ведёт список сообщений цикла и перед каждым
запросом возвращает его в бюджет, жертвуя наименее ценным:

1. старая история диалога — целыми ходами, с начала;
2. результаты инструментов прошлых итераций — заменяются пометкой, начиная со старых;
3. свежие результаты — обрезаются поровну: короткие остаются целиком, длинные делят остаток.

Не помогло (сам вопрос и вызовы не помещаются) — ``AppError`` ``context_overflow``: честная
ошибка вместо отказа модели.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import AppError
from app.modules.completions.prompt import BuiltPrompt
from app.modules.llm.tokens import TokenCounter

DROPPED_NOTE = (
    "[результат опущен: не помещается в контекст модели; "
    "если он нужен, вызовите инструмент снова с более узким запросом]"
)
TRUNCATED_NOTE = "\n\n[…результат обрезан: не помещается в контекст модели]"
# Меньше этого результат не обрезаем: обрывок в пару строк хуже честной пометки «опущен».
MIN_RESULT_TOKENS = 200


def schemas_tokens(counter: TokenCounter, schemas: list[dict[str, Any]]) -> int:
    """Описания инструментов шаблон чата вставляет в промпт — они занимают контекст."""
    return counter.count(json.dumps(schemas, ensure_ascii=False)) if schemas else 0


@dataclass
class ContextStats:
    budget: int
    history_dropped: int = 0  # сообщений истории убрано в цикле
    results_dropped: int = 0  # результатов заменено пометкой
    results_truncated: int = 0  # результатов обрезано
    peak_tokens: int = 0

    def trace(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "peak_tokens": self.peak_tokens,
            **{
                key: value
                for key, value in (
                    ("history_dropped", self.history_dropped),
                    ("tool_results_dropped", self.results_dropped),
                    ("tool_results_truncated", self.results_truncated),
                )
                if value
            },
        }


@dataclass
class LoopContext:
    """Сообщения одного ответа и их цена в токенах; ``messages`` уходит в запрос к модели."""

    messages: list[dict[str, Any]]
    costs: list[int]
    history: int  # сообщений истории сразу после системного промпта
    overhead: int
    counter: TokenCounter
    stats: ContextStats
    _fresh: list[int] = field(default_factory=list)  # индексы результатов текущей итерации
    _stale: list[int] = field(default_factory=list)  # индексы результатов прошлых итераций

    @classmethod
    def start(cls, prompt: BuiltPrompt, counter: TokenCounter) -> LoopContext:
        messages = list(prompt.messages)
        costs = list(prompt.costs) or [counter.count_messages([m]) for m in messages]
        context = cls(
            messages=messages,
            costs=costs,
            history=prompt.history_messages,
            overhead=prompt.overhead,
            counter=counter,
            stats=ContextStats(budget=prompt.budget),
        )
        context.stats.peak_tokens = context.used
        return context

    @property
    def used(self) -> int:
        return self.overhead + sum(self.costs)

    def add_calls(self, message: dict[str, Any]) -> None:
        """Сообщение ассистента с вызовами: начинается новая итерация."""
        self._stale.extend(self._fresh)
        self._fresh = []
        self._append(message)

    def add_result(self, call_id: str, content: str) -> None:
        self._fresh.append(len(self.messages))
        self._append({"role": "tool", "tool_call_id": call_id, "content": content})

    def fit(self) -> None:
        """Возвращает сообщения в бюджет перед следующим запросом к модели."""
        budget = self.stats.budget
        if self.used > budget:
            self._drop_history(budget)
        if self.used > budget:
            self._drop_stale(budget)
        if self.used > budget:
            self._truncate_fresh(budget)
        if self.used > budget:
            raise AppError(
                "Запрос и результаты инструментов не помещаются в контекст модели",
                code="context_overflow",
                status_code=413,
            )
        self.stats.peak_tokens = max(self.stats.peak_tokens, self.used)

    # ------------------------------------------------------------------ внутреннее

    @property
    def _note_cost(self) -> int:
        return self.counter.count(DROPPED_NOTE)

    def _append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self.costs.append(self.counter.count_messages([message]))

    def _replace(self, index: int, content: str) -> None:
        self.messages[index] = {**self.messages[index], "content": content}
        self.costs[index] = self.counter.count_messages([self.messages[index]])

    def _drop_history(self, budget: int) -> None:
        """Старые ходы — целиком: история по-прежнему начинается с вопроса пользователя."""
        while self.history and self.used > budget:
            removed = 0
            while self.history and (removed == 0 or self.messages[1]["role"] != "user"):
                del self.messages[1]
                del self.costs[1]
                self.history -= 1
                removed += 1
            self.stats.history_dropped += removed
            self._fresh = [i - removed for i in self._fresh]
            self._stale = [i - removed for i in self._stale]

    def _drop_stale(self, budget: int) -> None:
        for index in self._stale:
            if self.used <= budget:
                return
            if self.counter.count(self.messages[index]["content"]) <= self._note_cost:
                continue  # короче пометки (или уже она) — замена ничего не освободит
            self._replace(index, DROPPED_NOTE)
            self.stats.results_dropped += 1

    def _truncate_fresh(self, budget: int) -> None:
        if not self._fresh:
            return
        own = {i: self.counter.count(self.messages[i]["content"]) for i in self._fresh}
        available = budget - (self.used - sum(own.values()))
        # Делим остаток поровну; кто короче доли — остаётся целым и отдаёт излишек остальным.
        caps: dict[int, int] = {}
        left = available
        pending = sorted(own, key=lambda i: own[i])
        while pending:
            share = left // len(pending)
            index = pending.pop(0)
            caps[index] = min(own[index], share)
            left -= caps[index]
        for index, cap in caps.items():
            if cap >= own[index]:
                continue
            if cap < MIN_RESULT_TOKENS:
                self._replace(index, DROPPED_NOTE)
                self.stats.results_dropped += 1
            else:
                self._replace(index, self._cut(self.messages[index]["content"], own[index], cap))
                self.stats.results_truncated += 1

    def _cut(self, text: str, cost: int, cap: int) -> str:
        """Обрезает текст до ``cap`` токенов: по доле символов, с проверкой счётчиком."""
        target = cap - self.counter.count(TRUNCATED_NOTE)
        size = int(len(text) * target / cost)
        while size > 0:
            piece = text[:size]
            if self.counter.count(piece) <= target:
                return piece + TRUNCATED_NOTE
            size = int(size * 0.9)
        return DROPPED_NOTE
