"""Админка «Безопасность» (§13.4): блокировки IP и подсетей, доверенные подсети, проверка
событий входа. Просмотр — ``admin.logins.view``, изменения — ``admin.security.manage`` и аудит.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.modules.admin.schemas import LoginEventOut
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.rbac.permissions import Perm
from app.modules.security.bruteforce import BruteforceGuard
from app.modules.security.ipblocks import Blocklist, Network, parse_network
from app.modules.security.models import IpBlock, LoginEvent, TrustedNetwork
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.LOGINS_VIEW))]
Manager = Annotated[CurrentUser, Depends(require(Perm.SECURITY_MANAGE))]
# Шире этого — почти наверняка ошибка (заблокировать полсети компании одной строкой).
MIN_PREFIX = {4: 16, 6: 48}


class IpBlockOut(BaseModel):
    id: UUID
    cidr: str
    reason: str
    source: str
    until: datetime | None
    active: bool
    created_at: datetime
    created_by: str | None


class IpBlockIn(BaseModel):
    cidr: str = Field(
        min_length=2, max_length=64, description="IP или подсеть: 10.1.2.3, 10.1.2.0/24"
    )
    reason: str = Field(min_length=1, max_length=300)
    minutes: int | None = Field(None, gt=0, le=525_600, description="Срок; пусто — бессрочно.")


class TrustedOut(BaseModel):
    id: UUID
    cidr: str
    note: str | None
    created_at: datetime
    created_by: str | None


class TrustedIn(BaseModel):
    cidr: str = Field(min_length=2, max_length=64)
    note: str | None = Field(None, max_length=300)


def _blocklist(request: Request) -> Blocklist:
    blocklist: Blocklist = request.app.state.blocklist
    return blocklist


def _network(value: str) -> Network:
    try:
        network = parse_network(value)
    except ValueError as exc:
        raise AppError("Неверный IP или подсеть", code="bad_cidr", status_code=422) from exc
    if network.prefixlen < MIN_PREFIX[network.version]:
        raise AppError(
            f"Слишком широкая подсеть: не шире /{MIN_PREFIX[network.version]}",
            code="cidr_too_wide",
            status_code=422,
        )
    return network


async def _names(db: DbDep, ids: set[UUID | None]) -> dict[UUID, str]:
    real = {i for i in ids if i}
    if not real:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(real)))).all()
    return dict(rows)


@router.get("/ip-blocks", response_model=list[IpBlockOut], operation_id="adminListIpBlocks")
async def list_blocks(db: DbDep, _: Viewer, include_expired: bool = False) -> list[IpBlockOut]:
    now = utcnow()
    stmt = select(IpBlock)
    if not include_expired:
        stmt = stmt.where(or_(IpBlock.until.is_(None), IpBlock.until > now))
    rows = (await db.scalars(stmt.order_by(IpBlock.created_at.desc()).limit(500))).all()
    names = await _names(db, {r.created_by for r in rows})
    return [
        IpBlockOut(
            id=r.id,
            cidr=r.cidr,
            reason=r.reason,
            source=r.source,
            until=r.until,
            active=r.until is None or r.until > now,
            created_at=r.created_at,
            created_by=names.get(r.created_by) if r.created_by else None,
        )
        for r in rows
    ]


@router.post("/ip-blocks", response_model=IpBlockOut, status_code=201, operation_id="adminBlockIp")
async def block_ip(body: IpBlockIn, request: Request, db: DbDep, actor: Manager) -> IpBlockOut:
    network = _network(body.cidr)
    own = client_ip(request)
    if own and _contains(network, own):
        raise AppError("Нельзя заблокировать свой адрес", code="self_block", status_code=422)
    until = utcnow() + timedelta(minutes=body.minutes) if body.minutes else None
    row = IpBlock(
        cidr=str(network), reason=body.reason.strip(), until=until, source="manual",
        created_by=actor.id,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="ip.block", target_type="ip", target_id=str(network),
        details={"reason": row.reason, "until": until.isoformat() if until else None},
        ip=own,
    )  # fmt: skip
    await db.commit()
    await _blocklist(request).changed()
    return IpBlockOut(
        id=row.id, cidr=row.cidr, reason=row.reason, source=row.source, until=row.until,
        active=True, created_at=row.created_at, created_by=actor.user.full_name,
    )  # fmt: skip


def _contains(network: Network, ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.version == network.version and address in network


@router.delete("/ip-blocks/{block_id}", status_code=204, operation_id="adminUnblockIp")
async def unblock_ip(block_id: UUID, request: Request, db: DbDep, actor: Manager) -> None:
    row = await db.get(IpBlock, block_id)
    if row is None:
        raise NotFoundError("Блокировка не найдена")
    network = parse_network(row.cidr)
    await db.delete(row)
    await audit.record(
        db, actor_id=actor.id, action="ip.unblock", target_type="ip", target_id=row.cidr,
        details={"reason": row.reason, "source": row.source}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    if network.num_addresses == 1:
        # Автоблокировку за перебор держит и Redis — снимаем её тоже.
        guard: BruteforceGuard = request.app.state.bruteforce
        await guard.unlock_ip(str(network.network_address))
    await _blocklist(request).changed()


@router.get(
    "/trusted-networks", response_model=list[TrustedOut], operation_id="adminListTrustedNetworks"
)
async def list_trusted(db: DbDep, _: Viewer) -> list[TrustedOut]:
    rows = (await db.scalars(select(TrustedNetwork).order_by(TrustedNetwork.cidr))).all()
    names = await _names(db, {r.created_by for r in rows})
    return [
        TrustedOut(
            id=r.id,
            cidr=r.cidr,
            note=r.note,
            created_at=r.created_at,
            created_by=names.get(r.created_by) if r.created_by else None,
        )
        for r in rows
    ]


@router.post(
    "/trusted-networks",
    response_model=TrustedOut,
    status_code=201,
    operation_id="adminTrustNetwork",
)
async def trust(body: TrustedIn, request: Request, db: DbDep, actor: Manager) -> TrustedOut:
    network = _network(body.cidr)
    if await db.scalar(select(TrustedNetwork.id).where(TrustedNetwork.cidr == str(network))):
        raise AppError("Подсеть уже в доверенных", code="exists", status_code=409)
    row = TrustedNetwork(cidr=str(network), note=body.note, created_by=actor.id)
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="network.trust", target_type="ip", target_id=row.cidr,
        details={"note": body.note}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _blocklist(request).changed()
    return TrustedOut(
        id=row.id, cidr=row.cidr, note=row.note, created_at=row.created_at,
        created_by=actor.user.full_name,
    )  # fmt: skip


@router.delete(
    "/trusted-networks/{network_id}", status_code=204, operation_id="adminUntrustNetwork"
)
async def untrust(network_id: UUID, request: Request, db: DbDep, actor: Manager) -> None:
    row = await db.get(TrustedNetwork, network_id)
    if row is None:
        raise NotFoundError("Подсеть не найдена")
    await db.delete(row)
    await audit.record(
        db, actor_id=actor.id, action="network.untrust", target_type="ip", target_id=row.cidr,
        details={}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _blocklist(request).changed()


@router.post(
    "/logins/{event_id}/review", response_model=LoginEventOut, operation_id="adminReviewLogin"
)
async def review(event_id: UUID, request: Request, db: DbDep, actor: Manager) -> LoginEventOut:
    """Отметить событие входа проверенным (флаги риска разобраны)."""
    event = await db.get(LoginEvent, event_id)
    if event is None:
        raise NotFoundError("Событие не найдено")
    if event.reviewed_at is None:
        event.reviewed_at = utcnow()
        event.reviewed_by = actor.id
        await audit.record(
            db, actor_id=actor.id, action="login.review", target_type="login_event",
            target_id=event.id, details={"flags": event.risk_flags}, ip=client_ip(request),
        )  # fmt: skip
        await db.commit()
    return LoginEventOut.model_validate(event, from_attributes=True)
