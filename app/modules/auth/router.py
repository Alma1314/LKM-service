from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.err import BizError, ErrCode, ERRTABLE, map_err
from app.db.session import getdb
from app.modules.auth.schemas import UserLoginInfo, UserRegInfo
from app.modules.auth.service import login, register
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/reg", response_model=ApiResp)
def reg(user: UserRegInfo):
    with getdb() as conn:
        user_id = register(conn, user)

    _, ok_msg = ERRTABLE[ErrCode.OK]
    return ApiResp(code=ErrCode.OK, msg=ok_msg, data={"user_id": user_id})


@router.post("/login", response_model=ApiResp)
def login_route(user: UserLoginInfo):
    with getdb() as conn:
        user_id = login(conn, user)

    _, ok_msg = ERRTABLE[ErrCode.OK]
    return ApiResp(code=ErrCode.OK, msg=ok_msg, data={"user_id": user_id})
