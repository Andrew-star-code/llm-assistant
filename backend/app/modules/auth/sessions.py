"""Серверные сессии (§6.4, ADR-0004).

* В cookie — случайный непрозрачный токен; в Redis и Postgres — только его SHA-256.
* Redis ``sess:<hash>`` — активная сессия, TTL = тайм-аут простоя (продлевается при запросах,
  но не дальше абсолютного срока). ``user_sessions:<user_id>`` — хэши сессий пользователя,
  чтобы завершить их все разом (блокировка, «разлогинить»).
* Таблица ``sessions`` — история для админки; ``last_seen_at`` обновляется не чаще раза в 5 минут.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SessionSettings
from app.core.db import utcnow
from app.modules.auth.models import UserSession

LAST_SEEN_PERSIST_S = 300


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class SessionData:
    session_id: UUID
    user_id: UUID
    token_hash: str
    csrf_token: str
    provider: str
    expires_at: float


def _s(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _key(token_hash: str) -> str:
    return f"sess:{token_hash}"


def _user_key(user_id: UUID) -> str:
    return f"user_sessions:{user_id}"


class SessionStore:
    def __init__(self, redis: Redis, settings: SessionSettings) -> None:
        self.redis = redis
        self.settings = settings

    @property
    def idle_s(self) -> int:
        return self.settings.idle_timeout_minutes * 60

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: str,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[str, SessionData]:
        token = secrets.token_urlsafe(32)
        token_hash = hash_token(token)
        now = utcnow()
        expires = now + timedelta(hours=self.settings.absolute_timeout_hours)
        data = SessionData(
            session_id=uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            csrf_token=new_csrf_token(),
            provider=provider,
            expires_at=expires.timestamp(),
        )
        db.add(
            UserSession(
                id=data.session_id,
                user_id=user_id,
                token_hash=token_hash,
                provider=provider,
                created_at=now,
                last_seen_at=now,
                expires_at=expires,
                ip=ip,
                user_agent=(user_agent or "")[:1000] or None,
            )
        )
        await db.flush()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                _key(token_hash),
                mapping={
                    "session_id": str(data.session_id),
                    "user_id": str(user_id),
                    "csrf": data.csrf_token,
                    "provider": provider,
                    "expires_at": str(data.expires_at),
                    "persisted_at": str(time.time()),
                },
            )
            pipe.expire(_key(token_hash), min(self.idle_s, int(data.expires_at - time.time())))
            pipe.sadd(_user_key(user_id), token_hash)
            pipe.expire(_user_key(user_id), self.settings.absolute_timeout_hours * 3600)
            await pipe.execute()
        return token, data

    async def get(self, db: AsyncSession | None, token: str) -> SessionData | None:
        """Сессия по токену из cookie с продлением простоя; None — нет, истекла или отозвана."""
        token_hash = hash_token(token)
        raw = {_s(k): _s(v) for k, v in (await self.redis.hgetall(_key(token_hash))).items()}
        if not raw:
            return None
        expires_at = float(raw["expires_at"])
        now = time.time()
        if expires_at <= now:
            await self.redis.delete(_key(token_hash))
            return None
        await self.redis.expire(_key(token_hash), min(self.idle_s, int(expires_at - now)))
        data = SessionData(
            session_id=UUID(raw["session_id"]),
            user_id=UUID(raw["user_id"]),
            token_hash=token_hash,
            csrf_token=raw["csrf"],
            provider=raw.get("provider", ""),
            expires_at=expires_at,
        )
        if db is not None and now - float(raw.get("persisted_at", 0)) > LAST_SEEN_PERSIST_S:
            await self.redis.hset(_key(token_hash), "persisted_at", str(now))
            await db.execute(
                update(UserSession)
                .where(UserSession.id == data.session_id)
                .values(last_seen_at=datetime.fromtimestamp(now, UTC))
            )
            await db.commit()
        return data

    async def is_active(self, token_hash: str) -> bool:
        return bool(await self.redis.exists(_key(token_hash)))

    async def _revoke_rows(
        self, db: AsyncSession, rows: list[UserSession], by: UUID | None, reason: str
    ) -> int:
        now = utcnow()
        for row in rows:
            row.revoked_at = now
            row.revoked_by = by
            row.revoke_reason = reason
            await self.redis.delete(_key(row.token_hash))
            await self.redis.srem(_user_key(row.user_id), row.token_hash)
        await db.flush()
        return len(rows)

    async def revoke(
        self, db: AsyncSession, session_id: UUID, *, by: UUID | None, reason: str
    ) -> bool:
        row = await db.get(UserSession, session_id)
        if row is None or row.revoked_at is not None:
            return False
        await self._revoke_rows(db, [row], by, reason)
        return True

    async def revoke_user(
        self, db: AsyncSession, user_id: UUID, *, by: UUID | None, reason: str
    ) -> int:
        """Завершает все сессии пользователя (блокировка, отключение в AD, «разлогинить»)."""
        rows = list(
            (
                await db.scalars(
                    select(UserSession).where(
                        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
                    )
                )
            ).all()
        )
        count = await self._revoke_rows(db, rows, by, reason)
        # На случай рассинхрона с БД — удалить всё, что Redis знает о пользователе.
        hashes = await self.redis.smembers(_user_key(user_id))
        if hashes:
            await self.redis.delete(*(_key(_s(h)) for h in hashes))
        await self.redis.delete(_user_key(user_id))
        return count
