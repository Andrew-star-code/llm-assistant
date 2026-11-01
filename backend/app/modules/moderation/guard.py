"""Guard-модель (§9.6, SHOULD): проверка сообщения пользователя ролью ``guard`` (Qwen3Guard).

Ответ модели: «Safety: Safe|Unsafe|Controversial» и «Categories: …». Вердикт Unsafe создаёт
инцидент ``guard`` (не чаще одного на чат за ``report_window_s``, повторы — счётчик), даже если
основная модель репорт не вызвала. По умолчанию ничего не блокирует; если в админке включена
блокировка категорий, проверка идёт до ответа и сработавшая категория даёт нейтральный отказ.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.incidents import service as incidents
from app.modules.llm.registry import ModelRegistry

log = structlog.stdlib.get_logger("app.moderation.guard")

GUARD_ROLE = "guard"
_SAFETY = re.compile(r"Safety:\s*(Safe|Unsafe|Controversial)", re.IGNORECASE)
_CATEGORIES = re.compile(r"Categories:\s*(.+)", re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    label: str  # Safe | Unsafe | Controversial
    categories: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def unsafe(self) -> bool:
        return self.label == "Unsafe"

    def blocked_by(self, categories: list[str]) -> list[str]:
        wanted = {c.casefold() for c in categories}
        return [c for c in self.categories if c.casefold() in wanted] if self.unsafe else []


def parse(text: str) -> Verdict:
    safety = _SAFETY.search(text)
    label = safety.group(1).capitalize() if safety else "Safe"
    found = _CATEGORIES.search(text)
    names = [] if not found else [c.strip() for c in found.group(1).split(",")]
    return Verdict(label, [c for c in names if c and c.lower() != "none"], text.strip()[:500])


def available(settings: Settings) -> bool:
    return settings.moderation.guard_enabled and GUARD_ROLE in settings.models


async def classify(registry: ModelRegistry, settings: Settings, text: str) -> Verdict | None:
    """Вердикт guard-модели; недоступна — None (это забота монитора здоровья моделей)."""
    endpoint = registry.get(GUARD_ROLE)
    try:
        response = await asyncio.wait_for(
            registry.client(GUARD_ROLE).chat.completions.create(
                model=endpoint.model,
                messages=[{"role": "user", "content": text}],
                max_tokens=64,
                temperature=0,
            ),
            timeout=settings.moderation.guard_timeout_s,
        )
    except Exception as exc:
        log.warning("guard.failed", error=f"{type(exc).__name__}: {exc}"[:200])
        return None
    return parse(response.choices[0].message.content or "")


async def check(
    registry: ModelRegistry,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    text: str,
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
    blocked: list[str],
) -> Verdict | None:
    """Проверить сообщение; Unsafe — инцидент ``guard``."""
    verdict = await classify(registry, settings, text)
    if verdict is None or not verdict.unsafe:
        return verdict
    hit = verdict.blocked_by(blocked)
    window = settings.moderation.report_window_s
    payload: dict[str, Any] = {
        "verdict": verdict.label,
        "categories": verdict.categories,
        "raw": verdict.raw,
        "message_excerpt": text[:500],
        "blocked": bool(hit),
    }
    await incidents.report(
        sessions,
        type="guard",
        severity="high",
        title=f"Guard: {', '.join(verdict.categories) or 'Unsafe'}"
        + (" — ответ заблокирован" if hit else ""),
        fingerprint=f"guard:{chat_id}:{int(time.time() // window)}",
        payload=payload,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )
    return verdict
