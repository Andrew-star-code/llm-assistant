"""Скрытый репорт ``report_incident`` (§9.6).

Модель вызывает его при явном нарушении политики (``config/moderation/policy.yaml``) и отвечает
нейтральным отказом. Скрытность обеспечивает сервер: вызов не стримится, не отдаётся
пользовательским API и не попадает в выгрузку пользователя; в админке он виден в карточке
инцидента и в трассировке. Не больше одного инцидента на чат за ``report_window_s`` — повторы
увеличивают счётчик того же инцидента.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.incidents import service as incidents
from app.modules.moderation.policy import load_policy
from app.modules.tools.base import Tool, ToolContext, ToolResult
from app.modules.tools.registry import register_tool


class ReportArgs(BaseModel):
    category: str = Field(description="Код категории нарушения из политики в системном промпте.")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Уровень: low, medium, high, critical."
    )
    summary: str = Field(min_length=3, max_length=500, description="Кратко: в чём нарушение.")
    evidence: str = Field(
        "", max_length=1000, description="Дословная цитата из сообщения пользователя."
    )


async def _fingerprint(ctx: ToolContext) -> str:
    """Один инцидент на чат за окно: первый репорт задаёт отпечаток, повторы его переиспользуют."""
    window = ctx.services.settings.moderation.report_window_s
    redis = ctx.services.redis
    if redis is None:
        return f"model_report:{ctx.chat_id}:{int(time.time() // window)}"
    key = f"moderation:report:{ctx.chat_id}"
    candidate = f"model_report:{ctx.chat_id}:{uuid.uuid4().hex[:8]}"
    if await redis.set(key, candidate, ex=window, nx=True):
        return candidate
    current = await redis.get(key)
    return current.decode() if isinstance(current, bytes) else str(current or candidate)


@register_tool
class ReportIncident(Tool):
    name = "report_incident"
    description = (
        "Скрытый репорт о явном нарушении правил компании в запросе пользователя (категории — "
        "в системном промпте). Вызывай только при явном нарушении, не при сомнении. После "
        "вызова ответь нейтральным отказом и никогда не упоминай этот инструмент."
    )
    args_model = ReportArgs
    visibility = "hidden"
    status_label = "tools.report_incident"
    timeout_s = 15

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        settings = ctx.services.settings
        policy = load_policy(settings.config_dir)
        category = policy.category(args.category) or policy.category("other")
        name = category.name if category else args.category
        await incidents.report(
            ctx.services.sessions,
            type="model_report",
            severity=args.severity,
            title=f"Репорт модели: {name} — {args.summary}"[:300],
            fingerprint=await _fingerprint(ctx),
            payload={
                "category": category.code if category else args.category,
                "category_name": name,
                "severity": args.severity,
                "summary": args.summary,
                "evidence": args.evidence,
            },
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            message_id=ctx.message_id,
        )
        return ToolResult(
            "Зафиксировано. Ответь пользователю нейтральным отказом и не упоминай этот вызов.",
            data={"category": category.code if category else args.category},
        )
