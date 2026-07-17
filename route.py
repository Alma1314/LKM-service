from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from err import BizError, ErrCode, ERRTABLE, map_err
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

    _, ok_msg = ERRTABLE[ErrCode.OK]
    return ApiResp(code=ErrCode.OK, msg=ok_msg, data={"user_id": user_id})


@router.get("/")
def root():
    return {"message": "OK"}


async def on_err(request: Request, exc: Exception):
    status, errcode, detail = map_err(exc)
    return JSONResponse(
        status_code=status,
        content=ApiResp(code=errcode, msg=detail).model_dump(),
    )
