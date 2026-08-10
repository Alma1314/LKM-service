from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.errors import AuthErr
from app.db.models import Profile
from app.db.repo import get_or_raise
from app.modules.auth.schemas import ProfileInfo, ProfileUpdate


async def get_profile(db: AsyncSession, user_id: int) -> ProfileInfo:
    profile = await get_or_raise(db, Profile, AuthErr.USER_NOT_FOUND, Profile.user_id == user_id)
    return ProfileInfo.model_validate(profile)


async def update_profile(db: AsyncSession, user_id: int, info: ProfileUpdate) -> None:
    profile = await get_or_raise(db, Profile, AuthErr.USER_NOT_FOUND, Profile.user_id == user_id)
    if info.nickname is not None:
        profile.nickname = info.nickname
    if info.avatar is not None:
        profile.avatar = info.avatar
    await db.flush()
