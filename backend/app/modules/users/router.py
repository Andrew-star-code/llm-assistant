"""API профиля текущего пользователя: ``/api/profile``."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.deps import DbDep, StorageDep
from app.core.errors import NotFoundError
from app.modules.admin import app_settings
from app.modules.auth.deps import CurrentUserDep
from app.modules.rbac import service as rbac
from app.modules.users.profile import build_profile, photo_media_type
from app.modules.users.schemas import Profile, ProfileSettingsUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=Profile, operation_id="getProfile")
async def get_profile(request: Request, current: CurrentUserDep, db: DbDep) -> Profile:
    settings = await app_settings.effective(db, request.app.state.settings)
    return build_profile(current.user, current.roles, settings)


@router.patch("/settings", response_model=Profile, operation_id="updateProfileSettings")
async def update_settings(
    body: ProfileSettingsUpdate, request: Request, current: CurrentUserDep, db: DbDep
) -> Profile:
    settings = await app_settings.effective(db, request.app.state.settings)
    user = current.user
    if "address_form" in body.model_fields_set:
        user.address_form = body.address_form
    if "theme" in body.model_fields_set:
        user.settings = {**(user.settings or {}), "theme": body.theme}
    await db.commit()
    await db.refresh(user)
    return build_profile(user, await rbac.user_roles(db, user.id), settings)


@router.get(
    "/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "Фото нет"}},
    operation_id="getProfilePhoto",
)
async def get_photo(current: CurrentUserDep, storage: StorageDep) -> Response:
    data = await storage.get(current.user.photo_key) if current.user.photo_key else None
    if data is None:
        raise NotFoundError("Фото нет")
    return Response(
        data, media_type=photo_media_type(data), headers={"Cache-Control": "private, max-age=300"}
    )
