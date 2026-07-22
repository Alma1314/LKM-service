from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode
from app.db.models import Profile, User
from app.modules.auth.schemas import ProfileInfo, ProfileUpdate, UserLoginInfo, UserRegInfo
from app.modules.auth.security import hashpwd, verifypwd


def register(db: Session, info: UserRegInfo) -> int:
    existing = (
        db.query(User)
        .filter((User.username == info.username) | (User.email == info.email))
        .first()
    )
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED)

    user = User(username=info.username, email=info.email, hashed_password=hashpwd(info.password))
    db.add(user)
    db.flush()

    db.add(Profile(user_id=user.id))
    db.flush()
    return user.id


def login(db: Session, info: UserLoginInfo) -> int:
    user = db.query(User).filter(User.username == info.username).first()
    if not user:
        verifypwd(info.password, "$dummy$" + "a" * 64)
        raise BizError(ErrCode.INVALID_CREDENTIALS)
    if not verifypwd(info.password, user.hashed_password): # type: ignore[arg-type]
        raise BizError(ErrCode.INVALID_CREDENTIALS)
    return user.id # type: ignore[return-value]


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