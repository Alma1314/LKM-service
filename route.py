from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from err import BizError, ErrCode
from db import getdb
from model import ApiResp, UserRegInfo
from passwd import hashpwd

router = APIRouter()


@router.post("/reg", response_model=ApiResp)
def reg(user: UserRegInfo):
    with getdb() as conn:
        cur = conn.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (user.username, user.email),
        )
        if cur.fetchone():
            raise BizError(ErrCode.ALREADY_REGISTERED)

        hashed = hashpwd(user.password)
        cur = conn.execute(
            "INSERT INTO users (username, email, hpwd) VALUES (?, ?, ?)",
            (user.username, user.email, hashed),
        )
        user_id = cur.lastrowid

    return ApiResp(code=ErrCode.OK, msg=ErrCode.OK.msg(), data={"user_id": user_id})


@router.get("/")
def root():
    return {"message": "OK"}


async def on_biz_error(request: Request, exc: BizError):
    return JSONResponse(
        status_code=400,
        content=ApiResp(code=exc.errcode, msg=exc.detail).model_dump(),
    )
