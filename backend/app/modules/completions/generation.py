"""Генерация ответа (§2.2, §8): ``GenerationManager`` — жизненный цикл задач и порядок шагов.

Один ответ — одна asyncio-задача ``_run``:

1. ``preparation.prepare`` — всё из БД: ветка, сценарий, модель, системный промпт, вложения,
   область поиска, инструменты, история;
2. ``message.start`` и guard-модель (§9.6);
3. ``retrieval.auto_rag`` — авто-поиск по базам знаний (§8.3);
4. ``prompt.build_messages`` и ``toolloop.run_loop`` — модель и цикл инструментов (§8.4);
5. ``finish.finish`` — сохранение, токены и лимиты, заголовок, метрики, ``message.end``.

Общее состояние шагов — ``state.Deps`` и ``state.GenerationResult``.

* «Стоп» может попасть в любой процесс api: отмена — флаг ``gen:cancel:<id>`` в Redis; исполнитель
  проверяет его между чанками, закрывает запрос к модели и сохраняет частичный ответ (``stopped``).
* Остановка процесса: задачи отменяются и сохраняют ответ со статусом ``interrupted``; ответы,
  чьи исполнители умерли, помечает ``mark_orphaned_interrupted`` при старте.
* Где выполняется задача (ADR-0013): ``generation.mode = queue`` — ``start`` в api только ставит
  задание в Redis, задачу запускает сервис ``generator`` (``executor.py`` → ``launch``);
  ``inline`` — задача в процессе api.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import log_capture, metrics
from app.core.config import Settings
from app.core.storage import Storage
from app.modules.chats.models import Chat, Message
from app.modules.completions.context import LoopContext, schemas_tokens
from app.modules.completions.finish import fallback_title, finish
from app.modules.completions.preparation import Prepared, prepare
from app.modules.completions.prompt import (
    DEFAULT_CONTEXT,
    DEFAULT_RESERVE,
    PromptRenderer,
    build_messages,
)
from app.modules.completions.retrieval import auto_rag
from app.modules.completions.state import (
    Deps,
    GenerationResult,
    GuardBlocked,
    error_payload,
)
from app.modules.completions.streaming import (
    ALIVE_TTL_SECONDS,
    PROTOCOL_VERSION,
    QUEUE_KEY,
    EventWriter,
    alive_key,
    cancel_key,
)
from app.modules.completions.toolloop import run_loop
from app.modules.incidents.errors import report_exception
from app.modules.limits.service import Limits
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Usage
from app.modules.moderation import guard
from app.modules.moderation.guard import Verdict
from app.modules.tools.base import Services
from app.workers.dispatch import Dispatcher

log = structlog.stdlib.get_logger("app.completions")


class GenerationManager:
    def __init__(
        self,
        *,
        settings: Settings,
        redis: Redis,
        sessions: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        renderer: PromptRenderer,
        storage: Storage,
        dispatcher: Dispatcher,
        limits: Limits,
    ) -> None:
        self.settings = settings
        self.limits = limits
        self.redis = redis
        self.sessions = sessions
        self.background: set[asyncio.Task[Any]] = set()
        self.registry = registry
        self.renderer = renderer
        self.storage = storage
        self.services = Services(
            settings=settings,
            sessions=sessions,
            storage=storage,
            models=registry,
            dispatcher=dispatcher,
            redis=redis,
        )
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.deps = Deps(
            settings=settings,
            redis=redis,
            sessions=sessions,
            registry=registry,
            renderer=renderer,
            storage=storage,
            limits=limits,
            services=self.services,
        )

    # ------------------------------------------------------------------ управление

    async def start(self, message_id: UUID) -> None:
        """Запускает генерацию: задачей в этом процессе или заданием исполнителю (ADR-0013)."""
        # Ключ живости ставится до запуска: SSE-читатель, пришедший раньше первого события,
        # будет ждать, а не решит, что генерация умерла.
        if self.settings.generation.mode == "queue":
            # Пока задание ждёт исполнителя, ответ не осиротевший; не дождалось — ключ истечёт.
            await self.redis.set(
                alive_key(message_id), "1", ex=self.settings.generation.queue_ttl_seconds
            )
            request_id = structlog.contextvars.get_contextvars().get("request_id")
            job = {
                "message_id": str(message_id),
                "request_id": request_id,
                "enqueued_at": time.time(),  # для метрики ожидания в очереди
            }
            await self.redis.rpush(QUEUE_KEY, json.dumps(job))
            return
        await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
        self.launch(message_id)

    def launch(self, message_id: UUID, request_id: str | None = None) -> None:
        """Задача генерации в этом процессе. Ключ живости уже должен стоять.

        ``request_id`` — из задания очереди: строки лога исполнителя сходятся с запросом в api.
        """

        async def job() -> None:
            if request_id is not None:
                structlog.contextvars.bind_contextvars(
                    request_id=request_id, message_id=str(message_id)
                )
                log_capture.start_request()
            await self._run(message_id)

        def done(_: asyncio.Task[None]) -> None:
            self.tasks.pop(message_id, None)
            metrics.GENERATIONS_ACTIVE.set(len(self.tasks))

        task = asyncio.create_task(job(), name=f"generation:{message_id}")
        self.tasks[message_id] = task
        metrics.GENERATIONS_ACTIVE.set(len(self.tasks))
        task.add_done_callback(done)

    async def request_stop(self, message_id: UUID) -> None:
        await self.redis.set(cancel_key(message_id), "1", ex=ALIVE_TTL_SECONDS * 10)

    async def drain(self, grace_seconds: float) -> None:
        """Остановка без потерь: идущие ответы дорабатываются до ``grace_seconds``, остальные
        отменяются и сохраняются как ``interrupted``."""
        tasks = list(self.tasks.values())
        if tasks and grace_seconds > 0:
            log.info("completions.draining", active=len(tasks), grace_s=grace_seconds)
            await asyncio.wait(tasks, timeout=grace_seconds)
        await self.shutdown()

    async def shutdown(self) -> None:
        for pending in list(self.background):
            pending.cancel()
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def mark_orphaned_interrupted(self) -> int:
        """Ответы в статусе streaming без живого исполнителя → interrupted (§8.5).

        Вызывается при старте и периодически (``sweep_orphans``): процесс мог упасть или быть
        остановлен, не успев сохранить ответ. Ключ живости продлевает только работающая
        генерация, поэтому ответ упавшего процесса находится не позже чем через его TTL.
        Слот одновременной генерации такого ответа сразу возвращается в лимит.
        """
        released: list[tuple[UUID, UUID]] = []
        async with self.sessions() as db:
            rows = (
                await db.execute(
                    select(Message, Chat.user_id)
                    .join(Chat, Chat.id == Message.chat_id)
                    .where(Message.status == "streaming")
                )
            ).all()
            count = 0
            for message, user_id in rows:
                if message.id in self.tasks or await self.redis.exists(alive_key(message.id)):
                    continue
                message.status = "interrupted"
                message.error = {"code": "interrupted", "message": "Генерация прервана"}
                released.append((user_id, message.id))
                count += 1
            await db.commit()
        for user_id, message_id in released:
            await self.limits.release_slot(user_id, message_id)
        if count:
            log.warning("completions.orphans_interrupted", count=count)
        return count

    async def sweep_orphans(self) -> None:
        """Фоновая проверка «осиротевших» ответов раз в TTL ключа живости."""
        while True:
            await asyncio.sleep(ALIVE_TTL_SECONDS)
            try:
                await self.mark_orphaned_interrupted()
            except Exception:
                log.exception("completions.orphans_check_failed")

    # ------------------------------------------------------------------ генерация

    def _guard(
        self,
        question: str,
        user_id: UUID,
        chat_id: UUID,
        message_id: UUID,
        blocked: list[str],
    ) -> asyncio.Task[Verdict | None] | None:
        if not question or not guard.available(self.settings):
            return None
        task = asyncio.create_task(
            guard.check(
                self.registry, self.settings, self.sessions, text=question, user_id=user_id,
                chat_id=chat_id, message_id=message_id, blocked=blocked,
            )
        )  # fmt: skip
        # Ссылка на фоновую задачу, чтобы её не собрал сборщик мусора до завершения.
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    async def _keep_alive(self, message_id: UUID, result: GenerationResult) -> None:
        while True:
            await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
            # Слот одновременной генерации продлевается, пока генерация жива (§12.3).
            if result.user_id is not None:
                await self.limits.refresh_slot(result.user_id, message_id)
            await asyncio.sleep(ALIVE_TTL_SECONDS / 3)

    async def _run(self, message_id: UUID) -> None:
        """Один ответ от начала до конца: шаги по порядку, любой исход заканчивается ``finish``."""
        started = time.monotonic()
        writer = EventWriter(self.redis, message_id, self.settings.chat.stream_ttl_seconds)
        result = GenerationResult()
        keepalive = asyncio.create_task(self._keep_alive(message_id, result))
        trace: dict[str, Any] = {}
        try:
            async with self.sessions() as db:
                prepared = await prepare(self.deps, db, message_id, result)
            await self._announce(prepared, message_id, writer)
            await self._check_guard(prepared, message_id, writer, result, trace)
            knowledge, rag_trace = await self._retrieve(prepared, writer, result)
            await self._answer(prepared, message_id, writer, result, trace, started,
                               knowledge=knowledge, rag_trace=rag_trace)  # fmt: skip
        except GuardBlocked:
            pass  # нейтральный отказ уже в ответе, модель не вызывалась
        except asyncio.CancelledError:
            result.status = "interrupted"
            result.error = {"code": "interrupted", "message": "Генерация прервана"}
            await finish(self.deps, message_id, result, trace, started, writer, title_for=None)
            raise
        except Exception as exc:
            log.exception("completions.failed", message_id=str(message_id))
            result.status = "error"
            result.error = error_payload(exc)
            if result.error["code"] == "internal_error":
                # Ошибка нашего кода (не модели): инцидент со стеком и логами генерации.
                await report_exception(
                    self.sessions, exc,
                    context={"stage": "generation", "message_id": str(message_id)},
                    request_lines=log_capture.request_lines(),
                    message_id=message_id,
                )  # fmt: skip
            trace["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            await writer.emit("error", result.error)
        finally:
            keepalive.cancel()
        # Заголовок — служебной моделью по первому успешному ответу; если ответ остановлен или
        # упал — сразу из первых слов вопроса, чтобы чат не висел в истории безымянным.
        question, first = result.question, result.is_first_answer
        title_for = question if first and result.status == "completed" else None
        fallback = fallback_title(question) if first and not title_for and question else None
        await finish(
            self.deps, message_id, result, trace, started, writer,
            title_for=title_for, title_now=fallback,
        )  # fmt: skip

    # ------------------------------------------------------------------ шаги ответа

    async def _announce(self, p: Prepared, message_id: UUID, writer: EventWriter) -> None:
        await writer.emit(
            "message.start",
            {
                "message_id": str(message_id),
                "chat_id": str(p.chat_id),
                "parent_id": str(p.parent_id) if p.parent_id else None,
                "model": p.plan.endpoint.model,
                "thinking": p.plan.thinking,
                "protocol_version": PROTOCOL_VERSION,
            },
        )

    async def _check_guard(
        self,
        p: Prepared,
        message_id: UUID,
        writer: EventWriter,
        result: GenerationResult,
        trace: dict[str, Any],
    ) -> None:
        """Guard-модель (§9.6): фоном; при блокировке категорий — до ответа модели."""
        guard_task = self._guard(p.question, p.user_id, p.chat_id, message_id, p.guard_block)
        if guard_task is None or not p.guard_block:
            return
        verdict = await guard_task
        hit = verdict.blocked_by(p.guard_block) if verdict else []
        if not hit:
            return
        refusal = p.policy.refusal
        result.content.append(refusal)
        await writer.delta("content", refusal)
        result.finish_reason = "guard"
        trace.update(
            model_role=p.plan.role, model=p.plan.endpoint.model,
            guard={"verdict": verdict.label if verdict else None, "blocked": hit},
        )  # fmt: skip
        raise GuardBlocked

    async def _retrieve(
        self, p: Prepared, writer: EventWriter, result: GenerationResult
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Авто-поиск по базам знаний (§8.3): фрагменты для промпта и трассировка поиска."""
        if p.rag_mode != "auto" or p.scope.empty:
            return None, None
        return await auto_rag(
            self.deps, p.context, writer, result, question=p.question, history=p.history,
            budget=int(
                (p.plan.endpoint.context_length or DEFAULT_CONTEXT)
                * self.settings.rag.context_share
            ),
            counter=p.counter,
        )  # fmt: skip

    async def _answer(
        self,
        p: Prepared,
        message_id: UUID,
        writer: EventWriter,
        result: GenerationResult,
        trace: dict[str, Any],
        started: float,
        *,
        knowledge: str | None,
        rag_trace: dict[str, Any] | None,
    ) -> None:
        """Промпт в бюджете контекста → модель и цикл инструментов → оценка токенов."""
        plan, counter, tools = p.plan, p.counter, p.tools
        system = "\n\n".join(x for x in (p.base_system, knowledge, p.attachments.text) if x)
        schemas = [t.schema() for t in tools]
        budget = (plan.endpoint.context_length or DEFAULT_CONTEXT) - (
            plan.endpoint.max_output_tokens or DEFAULT_RESERVE
        )
        prompt = build_messages(
            system=system,
            history=p.history,
            message=p.question,
            endpoint=plan.endpoint,
            counter=counter,
            overhead=schemas_tokens(counter, schemas),
            # Место под результаты инструментов этого ответа (§8.3).
            history_reserve=int(budget * self.settings.tools.context_reserve_share) if tools else 0,
        )
        loop_context = LoopContext.start(prompt, counter)
        trace.update(
            {
                "model_role": plan.role,
                "model": plan.endpoint.model,
                "thinking": plan.thinking,
                **prompt.trace(),
                "rag_mode": p.rag_mode,
                "scenario": p.scenario_code,
                **({"rag": rag_trace} if rag_trace else {}),
                "attachments": {
                    "mode": p.attachments.mode,
                    "files": len(p.attachments.files),
                    "tokens": p.attachments.tokens,
                },
                "tools_offered": [t.name for t in tools],
            }
        )
        try:
            await run_loop(
                self.deps,
                message_id,
                plan.role,
                loop_context,
                plan.params,
                writer,
                result,
                started,
                schemas=schemas,
                allowed={t.name for t in tools},
                context=p.context,
            )
        finally:
            trace["context"] = loop_context.stats.trace()
            if result.model_retries:
                trace["model_retries"] = result.model_retries
        if result.usage is None:
            result.usage = Usage(
                prompt_tokens=prompt.prompt_tokens,
                completion_tokens=counter.count(
                    "".join(result.content) + "".join(result.reasoning)
                ),
                reasoning_tokens=counter.count("".join(result.reasoning)) or None,
            )
            trace["usage_estimated"] = True
