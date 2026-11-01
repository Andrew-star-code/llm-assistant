"""Подсчёт токенов для бюджета контекста (§8.3).

Если у модели задан локальный ``tokenizer`` (tokenizer.json), считаем им — точно. Иначе — оценка
по длине текста (с запасом): так работает дев-стенд с fake-llm.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from tokenizers import Tokenizer

log = structlog.stdlib.get_logger("app.llm.tokens")

# Служебные токены роли и разметки шаблона чата на каждое сообщение.
PER_MESSAGE_OVERHEAD = 6
# Для оценки без токенизатора: в русском тексте ~3 символа на токен; берём с запасом.
CHARS_PER_TOKEN = 2.8


@lru_cache(maxsize=8)
def _load(path: Path) -> Tokenizer | None:
    try:
        return Tokenizer.from_file(str(path))
    except Exception:
        log.warning("llm.tokenizer_unavailable", path=str(path))
        return None


class TokenCounter:
    def __init__(self, tokenizer_path: Path | None) -> None:
        self._tokenizer = _load(tokenizer_path) if tokenizer_path else None

    @property
    def exact(self) -> bool:
        return self._tokenizer is not None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer is not None:
            return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
        return math.ceil(len(text) / CHARS_PER_TOKEN)

    def count_messages(self, messages: Iterable[Mapping[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = message.get("content")
            total += PER_MESSAGE_OVERHEAD + self.count(content if isinstance(content, str) else "")
        return total
