"""``python -m app.cli ip …`` — блокировки IP из командной строки (§13.4).

На случай, когда админка недоступна: автоблокировка за перебор попала на адрес администратора
или NAT офиса, и войти, чтобы снять её, уже нельзя.

* ``ip list`` — активные блокировки;
* ``ip unblock <IP или подсеть>`` — снять блокировки: для адреса — все, что его содержат, для
  подсети — с точно таким CIDR. Снимает и блокировку за перебор в Redis, пишет аудит
  ``ip.unblock`` без автора и оповещает процессы api (``Blocklist.changed``).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import or_, select

import app.models  # noqa: F401 — регистрирует все таблицы (аудит ссылается на users)
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory, utcnow
from app.core.redis import create_redis
from app.modules.audit import service as audit
from app.modules.security.bruteforce import BruteforceGuard
from app.modules.security.ipblocks import Blocklist, contains, parse_network
from app.modules.security.models import IpBlock


async def _list(settings: Settings) -> int:
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as db:
            now = utcnow()
            rows = (
                await db.scalars(
                    select(IpBlock)
                    .where(or_(IpBlock.until.is_(None), IpBlock.until > now))
                    .order_by(IpBlock.created_at)
                )
            ).all()
    finally:
        await engine.dispose()
    if not rows:
        print("Активных блокировок нет")
    for row in rows:
        until = row.until.isoformat(timespec="minutes") if row.until else "бессрочно"
        print(f"{row.cidr:<20} {row.source:<6} до {until:<25} {row.reason}")
    return 0


async def _unblock(settings: Settings, value: str) -> int:
    try:
        target = parse_network(value)
    except ValueError:
        print(f"Неверный IP или подсеть: {value}")
        return 1
    single = target.num_addresses == 1
    address = str(target.network_address)
    engine = create_engine(settings)
    redis = create_redis(settings)
    try:
        async with create_session_factory(engine)() as db:
            rows = (await db.scalars(select(IpBlock))).all()
            matched = [
                r
                for r in rows
                if (contains([parse_network(r.cidr)], address) if single else r.cidr == str(target))
            ]
            for row in matched:
                await db.delete(row)
                await audit.record(
                    db, actor_id=None, action="ip.unblock", target_type="ip", target_id=row.cidr,
                    details={"reason": row.reason, "source": row.source, "via": "cli"},
                )  # fmt: skip
            await db.commit()
        if single:
            await BruteforceGuard(redis, settings.auth.bruteforce).unlock_ip(address)
        await Blocklist(ttl_s=settings.security.blocklist_cache_s, redis=redis).changed()
    finally:
        await redis.aclose()
        await engine.dispose()
    if matched:
        print("Сняты блокировки: " + ", ".join(r.cidr for r in matched))
    else:
        note = " (счётчик перебора сброшен)" if single else ""
        print(f"Блокировок для {target} в таблице нет{note}")
    return 0


def cmd_ip_list(settings: Settings) -> int:
    return asyncio.run(_list(settings))


def cmd_ip_unblock(settings: Settings, value: str) -> int:
    return asyncio.run(_unblock(settings, value))
