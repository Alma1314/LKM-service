from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode
from app.db.models import Profile, User
from app.modules.auth.schemas import ProfileInfo, ProfileUpdate


def get_profile(db: Session, user_id: int) -> ProfileInfo:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        raise BizError(ErrCode.USER_NOT_FOUND)
    return ProfileInfo(
        nickname=profile.nickname,  # type: ignore[arg-type]
        avatar=profile.avatar,  # type: ignore[arg-type]
        role=profile.role,  # type: ignore[arg-type]
    )


def update_profile(db: Session, user_id: int, info: ProfileUpdate) -> None:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        raise BizError(ErrCode.USER_NOT_FOUND)
    if info.nickname is not None:
        profile.nickname = info.nickname
    if info.avatar is not None:
        profile.avatar = info.avatar
    db.flush()