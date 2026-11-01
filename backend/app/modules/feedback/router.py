"""Лайк и дизлайк ответа с причинами и комментарием (§7.4)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.core.deps import DbDep
from app.core.errors import AppError
from app.modules.auth.deps import CurrentUserDep
from app.modules.chats import service as chats
from app.modules.chats.schemas import FeedbackIn, FeedbackOut
from app.modules.feedback.models import Feedback

router = APIRouter(tags=["feedback"])


@router.put(
    "/messages/{message_id}/feedback", response_model=FeedbackOut, operation_id="setFeedback"
)
async def set_feedback(
    message_id: UUID, body: FeedbackIn, db: DbDep, current: CurrentUserDep
) -> FeedbackOut:
    message, _ = await chats.get_message(db, current.id, message_id)
    if message.role != "assistant":
        raise AppError("Оценить можно только ответ ассистента", code="bad_message")
    reasons: list[str] = list(body.reasons) if body.rating == -1 else []
    row = await db.scalar(
        select(Feedback).where(Feedback.message_id == message.id, Feedback.user_id == current.id)
    )
    if row is None:
        row = Feedback(message_id=message.id, user_id=current.id, rating=body.rating)
        db.add(row)
    row.rating = body.rating
    row.reasons = reasons
    row.comment = body.comment.strip() if body.comment and body.comment.strip() else None
    await db.commit()
    return FeedbackOut.model_validate(row, from_attributes=True)


@router.delete("/messages/{message_id}/feedback", status_code=204, operation_id="clearFeedback")
async def clear_feedback(message_id: UUID, db: DbDep, current: CurrentUserDep) -> None:
    message, _ = await chats.get_message(db, current.id, message_id)
    await db.execute(
        delete(Feedback).where(Feedback.message_id == message.id, Feedback.user_id == current.id)
    )
    await db.commit()
