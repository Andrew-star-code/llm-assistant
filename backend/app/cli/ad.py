"""Команды AD и администраторов: ``ad check``, ``ad sync``, ``create-admin`` (§6.7)."""

from __future__ import annotations

import asyncio
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core import db as core_db
from app.core import redis as core_redis
from app.core.config import Settings
from app.core.storage import LocalStorage
from app.modules.auth.diagnostics import DiagnosticsReport, run_diagnostics
from app.modules.auth.providers.ldap import LdapDirectory
from app.modules.auth.service import normalize_login
from app.modules.auth.sessions import SessionStore
from app.modules.rbac import service as rbac
from app.modules.rbac.compute import compute_directory_roles
from app.modules.rbac.permissions import SUPERADMIN
from app.modules.users.models import User
from app.modules.users.service import upsert_from_directory
from app.modules.users.sync import sync_all


def make_directory(settings: Settings) -> LdapDirectory:
    def read_password() -> str:
        path: Path | None = settings.ldap.bind_password_file
        return path.read_text(encoding="utf-8").strip() if path else ""

    return LdapDirectory(settings.ldap, read_password=read_password)


def _mark(ok: bool) -> str:
    return "OK " if ok else "ERR"


def format_report(r: DiagnosticsReport) -> str:
    lines = [f"Диагностика AD для «{r.login}»", "", "Контроллеры:"]
    for c in r.controllers:
        tail = f" — {c.error}" if c.error else ""
        lines.append(f"  [{_mark(c.ok)}] {c.url} ({c.duration_ms} мс){tail}")
    bind_tail = f" — {r.service_bind.error}" if r.service_bind.error else ""
    lines.append(f"Bind сервисной учёткой: [{_mark(r.service_bind.ok)}]{bind_tail}")
    if not r.service_bind.ok:
        return "\n".join(lines)
    if not r.user_found or r.entry is None:
        lines.append("Пользователь: не найден")
        return "\n".join(lines)
    e = r.entry
    lines += [
        f"Запись: {e.dn}",
        f"objectGUID: {e.guid}",
        f"Учётка включена: {'нет' if e.disabled else 'да'}",
        f"В группе доступа: {'да' if e.in_access_group else 'НЕТ'}",
        "Атрибуты:",
        *(f"  {k:<20} {v if v is not None else '—'}" for k, v in e.attributes.items()),
        "Группы:",
        *(f"  {g}" for g in e.groups or ["—"]),
        f"ФИО: {r.full_name}  (отчество: {r.middle_name_source})",
        f"Обращение ({r.address_form}): {r.address or '«на вы» без имени'}",
        f"Отдел: {r.department or '—'}",
        "Роли:",
        *(f"  {x.code:<28} {x.name}  [{x.source}]" for x in r.roles or []),
    ]
    if not r.roles:
        lines.append("  —")
    if r.password_check is not None:
        tail = f" — {r.password_check.error}" if r.password_check.error else ""
        lines.append(f"Проверка пароля: [{_mark(r.password_check.ok)}]{tail}")
    lines.append(f"Итог: {'вход возможен' if r.ok else 'вход НЕ возможен'}")
    return "\n".join(lines)


def cmd_ad_check(settings: Settings, login: str, password_prompt: bool, as_json: bool) -> int:
    if "ldap" not in settings.auth.providers:
        print("Провайдер ldap выключен в auth.providers", file=sys.stderr)
        return 1
    password = getpass.getpass("Пароль пользователя: ") if password_prompt else None
    report = asyncio.run(run_diagnostics(make_directory(settings), settings, login, password))
    print(report.model_dump_json(indent=2) if as_json else format_report(report))
    return 0 if report.ok else 2


async def _sync(settings: Settings) -> int:
    engine = core_db.create_engine(settings)
    redis = core_redis.create_redis(settings)
    try:
        stats = await sync_all(
            core_db.create_session_factory(engine),
            make_directory(settings),
            settings=settings,
            storage=LocalStorage(settings.storage.root),
            sessions=SessionStore(redis, settings.auth.session),
        )
        print(json.dumps(stats.__dict__, ensure_ascii=False))
        return 0 if stats.errors == 0 else 2
    finally:
        await redis.aclose()
        await engine.dispose()


def cmd_ad_sync(settings: Settings) -> int:
    return asyncio.run(_sync(settings))


async def _create_admin(settings: Settings, raw_login: str) -> int:
    login = normalize_login(
        raw_login, netbios_domain=settings.ldap.netbios_domain, upn_suffix=settings.ldap.upn_suffix
    )
    engine = core_db.create_engine(settings)
    try:
        async with core_db.create_session_factory(engine)() as db:
            await rbac.ensure_system_rbac(db)
            user_obj = await db.scalar(select(User).where(User.login == login))
            if user_obj is None:
                if "ldap" not in settings.auth.providers:
                    print(f"Пользователь {login} ещё не входил в систему", file=sys.stderr)
                    return 1
                found = await asyncio.to_thread(make_directory(settings).lookup, login)
                if found is None:
                    print(f"Пользователь {login} не найден в AD", file=sys.stderr)
                    return 1
                user_obj = await upsert_from_directory(
                    db, found, settings=settings, storage=LocalStorage(settings.storage.root)
                )
                specs = compute_directory_roles(
                    found.rule_attributes(), found.groups, settings.ldap
                )
                await rbac.sync_directory_roles(db, user_obj.id, specs)
            granted = await rbac.grant_role(db, user_obj.id, SUPERADMIN)
            await db.commit()
            state = "назначен" if granted else "уже был"
            print(f"{user_obj.full_name} ({login}): superadmin {state}")
            return 0
    finally:
        await engine.dispose()


def cmd_create_admin(settings: Settings, login: str) -> int:
    return asyncio.run(_create_admin(settings, login))
