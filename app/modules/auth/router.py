from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode, respond
from app.db.session import get_session
from app.modules.auth.schemas import ProfileInfo, ProfileUpdate, UserIdData, UserLoginInfo, UserRegInfo
from app.modules.auth.security import get_current_user_id
from app.modules.auth.service import get_profile, login, register, update_profile
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/reg", response_model=ApiResp[UserIdData])
@respond
def reg(user: UserRegInfo, db: Session = Depends(get_session)):
    user_id = register(db, user)
    return {"user_id": user_id}


@router.post("/login", response_model=ApiResp[UserIdData])
@respond
def login_route(user: UserLoginInfo, db: Session = Depends(get_session)):
    user_id = login(db, user)
    return {"user_id": user_id}


@router.get("/{user_id}", response_model=ApiResp[ProfileInfo])
@respond
def get_user(user_id: int, db: Session = Depends(get_session)):
    profile = get_profile(db, user_id)
    return profile.model_dump()


@router.put("/{user_id}/profile", response_model=ApiResp[ProfileInfo])
@respond
def edit_profile(
    user_id: int,
    info: ProfileUpdate,
    cur: int = Depends(get_current_user_id),
    db: Session = Depends(get_session),
):
    if cur != user_id:
        raise BizError(ErrCode.FORBIDDEN)
    update_profile(db, user_id, info)
    profile = get_profile(db, user_id)
    return profile.model_dump()