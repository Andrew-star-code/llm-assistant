"""Сборка выгрузки переписки (§13.3): JSON (полная), XLSX (строка на сообщение), DOCX и PDF
(читаемая стенограмма).

Выгрузка админская: в неё входит всё, что видно в просмотре чата админом, включая удалённые
сообщения и скрытые вызовы инструментов. Чаты читаются пачками, чтобы большая выборка не
держала в памяти ORM-объекты целиком.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import chats as admin_chats
from app.modules.admin.chat_schemas import ChatFilter
from app.modules.chats.models import Chat, Message
from app.modules.feedback.models import Feedback
from app.modules.rag.models import MessageSource
from app.modules.scenarios.models import Scenario
from app.modules.tools.models import ToolCall
from app.modules.users.models import User

BATCH = 200
XLSX_CELL_LIMIT = 32_767
ROLE_TITLES = {"user": "Пользователь", "assistant": "Ассистент"}


class ExportTooLarge(Exception):  # noqa: N818
    """В выборке больше сообщений, чем ``exports.max_messages``."""


@dataclass
class ChatDump:
    chat: Chat
    user: User
    scenario: str | None
    messages: list[Message]
    tool_calls: dict[UUID, list[ToolCall]] = field(default_factory=dict)
    sources: dict[UUID, list[MessageSource]] = field(default_factory=dict)
    feedback: dict[UUID, Feedback] = field(default_factory=dict)


async def chat_ids(db: AsyncSession, spec: dict[str, Any], tz: str) -> list[UUID]:
    """Чаты выгрузки: один (``chat_id``) или все подходящие под фильтр, старые сначала."""
    if spec.get("chat_id"):
        return [UUID(str(spec["chat_id"]))]
    f = ChatFilter.model_validate(spec)
    sub = admin_chats.matching_chats(f, tz).subquery()
    rows = await db.scalars(
        select(Chat.id).where(Chat.id.in_(select(sub.c.id))).order_by(Chat.created_at, Chat.id)
    )
    return list(rows.all())


async def count_messages(db: AsyncSession, ids: Sequence[UUID]) -> int:
    total = 0
    for start in range(0, len(ids), 1000):
        part = ids[start : start + 1000]
        total += int(await db.scalar(select(func.count()).where(Message.chat_id.in_(part))) or 0)
    return total


async def dumps(db: AsyncSession, ids: Sequence[UUID]) -> AsyncIterator[ChatDump]:
    for start in range(0, len(ids), BATCH):
        part = list(ids[start : start + BATCH])
        rows = (
            await db.execute(
                select(Chat, User, Scenario.name)
                .join(User, User.id == Chat.user_id)
                .outerjoin(Scenario, Scenario.id == Chat.scenario_id)
                .where(Chat.id.in_(part))
            )
        ).all()
        by_chat = {chat.id: ChatDump(chat, user, scenario, []) for chat, user, scenario in rows}
        messages = (
            await db.scalars(
                select(Message)
                .where(Message.chat_id.in_(part))
                .order_by(Message.created_at, Message.id)
            )
        ).all()
        message_chat: dict[UUID, UUID] = {}
        for m in messages:
            by_chat[m.chat_id].messages.append(m)
            message_chat[m.id] = m.chat_id
        ids_ = list(message_chat)
        for i in range(0, len(ids_), 5000):
            chunk = ids_[i : i + 5000]
            for call in await db.scalars(
                select(ToolCall)
                .where(ToolCall.message_id.in_(chunk))
                .order_by(ToolCall.iteration, ToolCall.created_at)
            ):
                by_chat[message_chat[call.message_id]].tool_calls.setdefault(
                    call.message_id, []
                ).append(call)
            for src in await db.scalars(
                select(MessageSource)
                .where(MessageSource.message_id.in_(chunk))
                .order_by(MessageSource.index)
            ):
                by_chat[message_chat[src.message_id]].sources.setdefault(src.message_id, []).append(
                    src
                )
            for fb in await db.scalars(select(Feedback).where(Feedback.message_id.in_(chunk))):
                by_chat[message_chat[fb.message_id]].feedback[fb.message_id] = fb
        for chat_id in part:
            if chat_id in by_chat:
                yield by_chat[chat_id]
        db.expunge_all()  # пачка записана — ORM-объекты больше не нужны


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def chat_json(d: ChatDump) -> dict[str, Any]:
    return {
        "id": str(d.chat.id),
        "title": d.chat.title,
        "user": {
            "id": str(d.user.id),
            "login": d.user.login,
            "full_name": d.user.full_name,
            "department": d.user.department,
        },
        "scenario": d.scenario,
        "is_test": d.chat.is_test,
        "created_at": _iso(d.chat.created_at),
        "last_message_at": _iso(d.chat.last_message_at),
        "deleted_at": _iso(d.chat.deleted_at),
        "active_leaf_id": str(d.chat.active_leaf_id) if d.chat.active_leaf_id else None,
        "messages": [
            {
                "id": str(m.id),
                "parent_id": str(m.parent_id) if m.parent_id else None,
                "role": m.role,
                "content": m.content,
                "reasoning": m.reasoning,
                "status": m.status,
                "model": m.model,
                "thinking": m.thinking,
                "finish_reason": m.finish_reason,
                "prompt_tokens": m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
                "reasoning_tokens": m.reasoning_tokens,
                "ttft_ms": m.ttft_ms,
                "latency_ms": m.latency_ms,
                "error": m.error,
                "trace": m.trace,
                "created_at": _iso(m.created_at),
                "deleted_at": _iso(m.deleted_at),
                "feedback": (
                    {
                        "rating": fb.rating,
                        "reasons": fb.reasons,
                        "comment": fb.comment,
                        "created_at": _iso(fb.created_at),
                    }
                    if (fb := d.feedback.get(m.id))
                    else None
                ),
                "tool_calls": [
                    {
                        "tool": c.tool,
                        "visibility": c.visibility,
                        "status": c.status,
                        "arguments": c.arguments,
                        "result_preview": c.result_preview,
                        "duration_ms": c.duration_ms,
                        "iteration": c.iteration,
                    }
                    for c in d.tool_calls.get(m.id, [])
                ],
                "sources": [
                    {
                        "index": s.index,
                        "kind": s.kind,
                        "title": s.title,
                        "kb_name": s.kb_name,
                        "page": s.page,
                        "section": s.section,
                        "snippet": s.snippet,
                        "score": s.score,
                        "cited": s.cited,
                    }
                    for s in d.sources.get(m.id, [])
                ],
            }
            for m in d.messages
        ],
    }


async def build_json(db: AsyncSession, ids: Sequence[UUID]) -> bytes:
    out = io.StringIO()
    out.write('{"chats": [\n')
    first = True
    async for d in dumps(db, ids):
        out.write(("" if first else ",\n") + json.dumps(chat_json(d), ensure_ascii=False))
        first = False
    out.write("\n]}\n")
    return out.getvalue().encode("utf-8")


XLSX_COLUMNS = (
    ("Чат", 38),
    ("Название чата", 30),
    ("Логин", 14),
    ("ФИО", 28),
    ("Отдел", 22),
    ("Сценарий", 18),
    ("Время", 18),
    ("Роль", 12),
    ("Текст", 80),
    ("Статус", 11),
    ("Модель", 20),
    ("Токены запроса", 10),
    ("Токены ответа", 10),
    ("До первого токена, мс", 10),
    ("Длительность, мс", 10),
    ("Оценка", 8),
    ("Причины", 18),
    ("Комментарий", 30),
    ("Инструменты", 24),
    ("Удалено", 18),
    ("id сообщения", 38),
    ("id родителя", 38),
)


def xlsx_cell(text: str | None) -> str | None:
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if text is None:
        return None
    clean = ILLEGAL_CHARACTERS_RE.sub("", text)
    return clean if len(clean) <= XLSX_CELL_LIMIT else clean[: XLSX_CELL_LIMIT - 1] + "…"


async def build_xlsx(db: AsyncSession, ids: Sequence[UUID], tz: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    zone = ZoneInfo(tz)
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Сообщения")
    for index, (_, width) in enumerate(XLSX_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    header = []
    for title, _ in XLSX_COLUMNS:
        cell = WriteOnlyCell(sheet, value=title)
        cell.font = Font(bold=True)
        header.append(cell)
    sheet.append(header)

    def local(value: datetime | None) -> datetime | None:
        # Excel не хранит часовой пояс: время записывается в поясе компании.
        return value.astimezone(zone).replace(tzinfo=None) if value else None

    async for d in dumps(db, ids):
        for m in d.messages:
            fb = d.feedback.get(m.id)
            calls = d.tool_calls.get(m.id, [])
            deleted = m.deleted_at or d.chat.deleted_at
            sheet.append(
                [
                    str(d.chat.id),
                    xlsx_cell(d.chat.title),
                    d.user.login,
                    d.user.full_name,
                    d.user.department,
                    d.scenario,
                    local(m.created_at),
                    ROLE_TITLES.get(m.role, m.role),
                    xlsx_cell(m.content),
                    m.status,
                    m.model,
                    m.prompt_tokens,
                    m.completion_tokens,
                    m.ttft_ms,
                    m.latency_ms,
                    fb.rating if fb else None,
                    ", ".join(fb.reasons) if fb and fb.reasons else None,
                    xlsx_cell(fb.comment) if fb else None,
                    ", ".join(
                        f"{c.tool}{' (скрытый)' if c.visibility == 'hidden' else ''}" for c in calls
                    )
                    or None,
                    local(deleted),
                    str(m.id),
                    str(m.parent_id) if m.parent_id else None,
                ]
            )
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(XLSX_COLUMNS))}1"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _when(value: datetime, zone: ZoneInfo) -> str:
    return value.astimezone(zone).strftime("%d.%m.%Y %H:%M")


async def build_markdown(db: AsyncSession, ids: Sequence[UUID], tz: str) -> str:
    """Стенограмма: чаты по порядку, сообщения всех веток по времени, пометки об удалении."""
    zone = ZoneInfo(tz)
    parts: list[str] = []
    async for d in dumps(db, ids):
        title = d.chat.title or "Без названия"
        head = [
            f"# {title}",
            "",
            f"**Пользователь:** {d.user.full_name} ({d.user.login})"
            + (f", {d.user.department}" if d.user.department else ""),
            f"**Создан:** {_when(d.chat.created_at, zone)}"
            + (f" · **Сценарий:** {d.scenario}" if d.scenario else "")
            + (" · тестовый чат" if d.chat.is_test else ""),
        ]
        if d.chat.deleted_at:
            head.append(f"**Удалён пользователем:** {_when(d.chat.deleted_at, zone)}")
        parts.append("\n\n".join(head))
        siblings: dict[UUID | None, int] = {}
        for m in d.messages:
            n = siblings[m.parent_id] = siblings.get(m.parent_id, 0) + 1
            meta = [ROLE_TITLES.get(m.role, m.role), _when(m.created_at, zone)]
            if m.role == "assistant":
                if n > 1:
                    meta.append(f"версия {n}")
                if m.model:
                    meta.append(m.model)
                if m.status != "completed":
                    meta.append(f"статус: {m.status}")
            if m.deleted_at:
                meta.append(f"удалено пользователем {m.deleted_at.astimezone(zone):%d.%m}")
            block = [f"### {' · '.join(meta)}"]
            if m.reasoning:
                block.append("> *Размышления:* " + m.reasoning.replace("\n", "\n> "))
            for c in d.tool_calls.get(m.id, []):
                hidden = " (скрытый)" if c.visibility == "hidden" else ""
                block.append(f"*Инструмент `{c.tool}`{hidden}: {c.status}, {c.duration_ms} мс*")
            block.append(m.content or "*(пусто)*")
            fb = d.feedback.get(m.id)
            if fb:
                mark = "нравится" if fb.rating > 0 else "не нравится"
                extra = ", ".join(fb.reasons) + (f" — {fb.comment}" if fb.comment else "")
                block.append(f"*Оценка: {mark}{' ' + extra if extra.strip(' —') else ''}*")
            parts.append("\n\n".join(block))
        parts.append("---")
    return "\n\n".join(parts) if parts else "*Нет чатов по выбранному фильтру.*"
