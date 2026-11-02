"""Идентичность пользователя от ``api`` (§9.5): подписанный служебный заголовок.

``X-DG-Identity`` — base64url(JSON: user_id, login, roles, department, admin, ts),
``X-DG-Signature`` — HMAC-SHA256 общим секретом. Модель не видит ни секрета, ни заголовков
и подменить их не может.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

MAX_SKEW_S = 60


@dataclass(frozen=True)
class Identity:
    user_id: str
    login: str
    roles: frozenset[str]
    department: str | None = None
    admin: bool = False  # админка «Источники данных»: виден весь каталог


class IdentityError(Exception):
    pass


def sign(identity: Identity, secret: str, now: float | None = None) -> dict[str, str]:
    payload = {
        "user_id": identity.user_id,
        "login": identity.login,
        "roles": sorted(identity.roles),
        "department": identity.department,
        "admin": identity.admin,
        "ts": int(now if now is not None else time.time()),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return {"X-DG-Identity": raw, "X-DG-Signature": mac}


def verify(
    raw: str | None, signature: str | None, secret: str, now: float | None = None
) -> Identity:
    if not raw or not signature:
        raise IdentityError("нет подписи")
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise IdentityError("неверная подпись")
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except ValueError as exc:
        raise IdentityError("повреждённый заголовок") from exc
    if abs((now if now is not None else time.time()) - int(data.get("ts", 0))) > MAX_SKEW_S:
        raise IdentityError("подпись устарела")
    return Identity(
        user_id=str(data["user_id"]),
        login=str(data["login"]),
        roles=frozenset(str(r) for r in data.get("roles", [])),
        department=data.get("department") or None,
        admin=bool(data.get("admin", False)),
    )
