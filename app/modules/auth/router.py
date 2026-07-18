from fastapi import APIRouter, Depends

from app.core.err import BizError, ErrCode, respond
from app.db.session import getdb
from app.modules.auth.schemas import ProfileUpdate, UserLoginInfo, UserRegInfo
from app.modules.auth.security import get_current_user_id
from app.modules.auth.service import get_profile, login, register, update_profile
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/reg", response_model=ApiResp)
@respond
def reg(user: UserRegInfo):
    with getdb() as conn:
        user_id = register(conn, user)
    return {"user_id": user_id}


@router.post("/login", response_model=ApiResp)
@respond
def login_route(user: UserLoginInfo):
    with getdb() as conn:
        user_id = login(conn, user)
    return {"user_id": user_id}


@router.get("/{user_id}", response_model=ApiResp)
@respond
def get_user(user_id: int):
    with getdb() as conn:
        profile = get_profile(conn, user_id)
    return profile.model_dump()


@router.put("/{user_id}/profile", response_model=ApiResp)
@respond
def edit_profile(user_id: int, info: ProfileUpdate, cur: int = Depends(get_current_user_id)):
    if cur != user_id:
        raise BizError(ErrCode.FORBIDDEN)
    with getdb() as conn:
        update_profile(conn, user_id, info)
        profile = get_profile(conn, user_id)
    return profile.model_dump()
