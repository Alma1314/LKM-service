from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import svc
from db import getdb
from err import BizError, ErrCode, ERRTABLE, map_err
from model import ApiResp, UserLoginInfo, UserRegInfo

router = APIRouter()


@router.post("/reg", response_model=ApiResp)
def reg(user: UserRegInfo):
    with getdb() as conn:
        user_id = svc.register(conn, user)

    _, ok_msg = ERRTABLE[ErrCode.OK]
    return ApiResp(code=ErrCode.OK, msg=ok_msg, data={"user_id": user_id})


@router.post("/login", response_model=ApiResp)
def login(user: UserLoginInfo):
    with getdb() as conn:
        user_id = svc.login(conn, user)

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
