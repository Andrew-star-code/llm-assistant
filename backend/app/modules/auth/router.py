"""API входа: ``/api/auth/*`` (§6.2, §6.4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError
from app.modules.admin import app_settings
from app.modules.admin.app_settings import first_login_notice
from app.modules.auth.deps import CurrentUser, CurrentUserDep, client_ip, optional_session
from app.modules.auth.providers.base import AuthFailure
from app.modules.auth.providers.dev import DevProvider
from app.modules.auth.schemas import CsrfOut, DevUserOut, LoginIn, Me, Notice, ProvidersOut
from app.modules.auth.service import LoginService
from app.modules.auth.sessions import SessionData, SessionStore, new_csrf_token
from app.modules.rbac import service as rbac
from app.modules.users.profile import role_out
from app.modules.users.schemas import UserSettings
from app.modules.users.service import address_of

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Неверный логин или пароль"


def _set_cookies(response: Response, settings: Settings, *, token: str | None, csrf: str) -> None:
    session = settings.auth.session
    if token is not None:
        response.set_cookie(
            session.cookie_name,
            token,
            max_age=session.absolute_timeout_hours * 3600,
            httponly=True,
            secure=session.cookie_secure,
            samesite="lax",
            path="/",
        )
    # CSRF-cookie читает фронтенд и повторяет в заголовке X-CSRF-Token (double submit).
    response.set_cookie(
        session.csrf_cookie_name,
        csrf,
        max_age=session.absolute_timeout_hours * 3600,
        httponly=False,
        secure=session.cookie_secure,
        samesite="lax",
        path="/",
    )


async def build_me(db: DbDep, current: CurrentUser, settings: Settings) -> Me:
    user = current.user
    settings = await app_settings.effective(db, settings)
    return Me(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        first_name=user.first_name,
        middle_name=user.middle_name,
        address=address_of(user, settings),
        title=user.title,
        department=user.department,
        has_photo=user.photo_key is not None,
        roles=role_out(current.roles),
        permissions=sorted(current.permissions),
        settings=UserSettings.model_validate(user.settings or {}),
        notice=Notice(
            required=await app_settings.notice_required(db, user.notice_accepted_at),
            text=await first_login_notice(db, settings),
        ),
    )


@router.get("/providers", response_model=ProvidersOut, operation_id="getAuthProviders")
async def providers(request: Request) -> ProvidersOut:
    settings: Settings = request.app.state.settings
    login_service: LoginService = request.app.state.login_service
    dev_users: list[DevUserOut] = []
    dev = login_service.providers.get("dev")
    if isinstance(dev, DevProvider):
        dev_users = [
            DevUserOut(
                login=u.login,
                full_name=u.full_name_raw or u.login,
                title=u.title,
                department=u.department,
            )
            for u in dev.list_users()
        ]
    return ProvidersOut(providers=list(settings.auth.providers), dev_users=dev_users)


@router.get("/csrf", response_model=CsrfOut, operation_id="getCsrfToken")
async def csrf(
    request: Request,
    response: Response,
    session: Annotated[SessionData | None, Depends(optional_session)],
) -> CsrfOut:
    """Выдаёт CSRF-cookie до входа; после входа токен привязан к сессии."""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.auth.session.csrf_cookie_name) or new_csrf_token()
    if session is not None:
        token = session.csrf_token
    _set_cookies(response, settings, token=None, csrf=token)
    return CsrfOut(csrf_token=token)


@router.post(
    "/login",
    response_model=Me,
    responses={401: {"description": INVALID_CREDENTIALS}},
    operation_id="login",
)
async def login(body: LoginIn, request: Request, response: Response, db: DbDep) -> Me:
    settings: Settings = request.app.state.settings
    service: LoginService = request.app.state.login_service
    try:
        result = await service.login(
            db,
            provider=body.provider,
            login=body.login,
            password=body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthFailure:
        raise AppError(INVALID_CREDENTIALS, code="invalid_credentials", status_code=401) from None
    _set_cookies(response, settings, token=result.token, csrf=result.session.csrf_token)
    roles = await rbac.user_roles(db, result.user.id)
    granted = await rbac.permissions_for_roles(db, (r.role.id for r in roles))
    current = CurrentUser(
        result.user, result.session, roles, rbac.effective_permissions(roles, granted)
    )
    return await build_me(db, current, settings)


@router.post("/logout", status_code=204, operation_id="logout")
async def logout(request: Request, response: Response, db: DbDep, current: CurrentUserDep) -> None:
    settings: Settings = request.app.state.settings
    store: SessionStore = request.app.state.sessions
    await store.revoke(db, current.session.session_id, by=current.id, reason="logout")
    await db.commit()
    response.delete_cookie(settings.auth.session.cookie_name, path="/")
    response.delete_cookie(settings.auth.session.csrf_cookie_name, path="/")


@router.get("/me", response_model=Me, operation_id="getMe")
async def me(request: Request, db: DbDep, current: CurrentUserDep) -> Me:
    return await build_me(db, current, request.app.state.settings)


@router.post("/notice/accept", status_code=204, operation_id="acceptNotice")
async def accept_notice(db: DbDep, current: CurrentUserDep) -> None:
    """Пользователь подтвердил уведомление о хранении переписки (§7.10, §15)."""
    if await app_settings.notice_required(db, current.user.notice_accepted_at):
        current.user.notice_accepted_at = utcnow()
        await db.commit()
