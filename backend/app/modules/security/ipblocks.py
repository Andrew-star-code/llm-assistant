"""Блокировки IP и подсетей, доверенные подсети (§13.4).

Активные блокировки и доверенные подсети процесс держит в памяти: проверка идёт на каждом
запросе к API. Изменение в админке или автоблокировка увеличивают версию в Redis — каждый
процесс сверяет её (один GET) и перечитывает таблицы сразу; без изменений — не чаще раза в
``blocklist_cache_s`` секунд (истекают сроки блокировок).
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.modules.security.models import IpBlock, TrustedNetwork

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_network(value: str) -> Network:
    """``10.0.0.5`` → ``10.0.0.5/32``; ``10.1.2.0/24`` как есть; иначе ValueError."""
    return ipaddress.ip_network(value.strip(), strict=False)


def subnet_of(ip: str, prefix_v4: int, prefix_v6: int) -> Network | None:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = prefix_v4 if address.version == 4 else prefix_v6
    return ipaddress.ip_network(f"{address}/{prefix}", strict=False)


def contains(networks: list[Network], ip: str | None) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in net for net in networks if net.version == address.version)


VERSION_KEY = "security:blocklist:version"


@dataclass
class Blocklist:
    ttl_s: int
    redis: Redis | None = None
    _loaded_at: float = 0.0
    _version: bytes | str | None = None
    _blocked: list[Network] = field(default_factory=list)
    _trusted: list[Network] = field(default_factory=list)

    async def changed(self) -> None:
        """Блокировки изменились: перечитать во всех процессах."""
        self._loaded_at = 0.0
        if self.redis is not None:
            await self.redis.incr(VERSION_KEY)

    async def _refresh(self, db: AsyncSession) -> None:
        version = await self.redis.get(VERSION_KEY) if self.redis is not None else None
        fresh = self.ttl_s and time.monotonic() - self._loaded_at < self.ttl_s
        if fresh and version == self._version:
            return
        self._version = version
        now = utcnow()
        blocked = (
            await db.scalars(
                select(IpBlock.cidr).where(or_(IpBlock.until.is_(None), IpBlock.until > now))
            )
        ).all()
        trusted = (await db.scalars(select(TrustedNetwork.cidr))).all()
        self._blocked = [parse_network(c) for c in blocked]
        self._trusted = [parse_network(c) for c in trusted]
        self._loaded_at = time.monotonic()

    async def blocked(self, db: AsyncSession, ip: str | None) -> bool:
        await self._refresh(db)
        return contains(self._blocked, ip)

    async def trusted(self, db: AsyncSession, ip: str | None) -> bool:
        await self._refresh(db)
        return contains(self._trusted, ip)
