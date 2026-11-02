"""Клиент ``data-gateway`` (§9.5).

Идентичность пользователя (логин, роли, отдел) ``api`` берёт из БД по сессии и подписывает HMAC
общим секретом; модель её не видит и подменить не может. Формат — ``services/data-gateway``
(``identity.py``): base64url(JSON) в ``X-DG-Identity`` и подпись в ``X-DG-Signature``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.rbac import service as rbac
from app.modules.users.models import User


@dataclass(frozen=True)
class Identity:
    user_id: str
    login: str
    roles: tuple[str, ...]
    department: str | None
    admin: bool = False


class GatewayError(Exception):
    """Ответ шлюза с ошибкой: ``code`` — rejected, query_failed, not_found, unavailable."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


async def identity_of(db: AsyncSession, user_id: UUID, *, admin: bool = False) -> Identity:
    user = await db.get(User, user_id)
    if user is None:
        raise GatewayError("forbidden", "пользователь не найден")
    roles = await rbac.user_roles(db, user_id)
    return Identity(
        user_id=str(user.id),
        login=user.login,
        roles=tuple(sorted(r.role.code for r in roles)),
        department=user.department,
        admin=admin,
    )


def sign(identity: Identity, secret: str, now: float | None = None) -> dict[str, str]:
    payload = {
        "user_id": identity.user_id,
        "login": identity.login,
        "roles": list(identity.roles),
        "department": identity.department,
        "admin": identity.admin,
        "ts": int(now if now is not None else time.time()),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return {"X-DG-Identity": raw, "X-DG-Signature": mac}


class DataGateway:
    def __init__(self, settings: Settings) -> None:
        config = settings.data_gateway
        if not config.url or config.secret is None:
            raise GatewayError("unavailable", "шлюз данных не настроен")
        self.url = config.url.rstrip("/")
        self.secret = config.secret.get_secret_value()
        self.timeout_s = config.timeout_s

    async def _request(
        self, method: str, path: str, identity: Identity, **kwargs: Any
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.request(
                    method, f"{self.url}{path}", headers=sign(identity, self.secret), **kwargs
                )
        except httpx.HTTPError as exc:
            raise GatewayError("unavailable", "шлюз данных недоступен") from exc
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GatewayError("unavailable", f"шлюз ответил {response.status_code}") from exc
        if response.status_code >= 400:
            error = body.get("error") or {}
            raise GatewayError(
                str(error.get("code", "error")),
                str(error.get("message", "ошибка шлюза")),
                response.status_code,
            )
        return body

    async def catalog(self, identity: Identity) -> dict[str, Any]:
        return await self._request("GET", "/v1/catalog", identity)

    async def describe(self, identity: Identity, name: str, question: str | None) -> dict[str, Any]:
        params = {"question": question} if question else None
        return await self._request("GET", f"/v1/datasets/{name}", identity, params=params)

    async def call(self, identity: Identity, name: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/v1/functions/{name}", identity, json={"params": params}
        )

    async def query(self, identity: Identity, sql: str) -> dict[str, Any]:
        return await self._request("POST", "/v1/query", identity, json={"sql": sql})
