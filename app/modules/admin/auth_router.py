"""
后台 cookie 会话端点：/admin/auth/login|refresh|logout|me。
"""

import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.err import CommonErr, resp_json, respond
from app.db.models import User, now_iso
from app.db.repo import consume_once, get_or_raise
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser
from app.modules.auth.errors import AuthErr
from app.modules.auth.models import RefreshToken
from app.modules.auth.security import verifypwd
from app.modules.auth.service_auth import generate_refresh_token, hash_refresh_token
from app.modules.auth.service_verify import check_code_rate_limit

from .deps import (
    COOKIE_NAME,
    COOKIE_PATH,
    REFRESH_NAME,
    create_admin_access_token,
    get_real_client_ip,
    require_admin,
)
from .schemas import AdminLoginReq, AdminUserOut

router = APIRouter(prefix="/admin", tags=["admin-auth"])

REFRESH_TOKEN_DAYS = 7


def _set_access_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,  # 生产 https 强制 Secure；开发 http 免加密
        samesite="lax",
        max_age=15 * 60,
        path=COOKIE_PATH,
    )


def _set_refresh_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key=REFRESH_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=REFRESH_TOKEN_DAYS * 86400,
        path=COOKIE_PATH,
    )


def _clear_cookies(resp: Response) -> None:
    resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    resp.delete_cookie(REFRESH_NAME, path=COOKIE_PATH)


def _admin_user_payload(user: User) -> dict[str, Any]:
    return AdminUserOut.model_validate(user).model_dump(mode="json")


@router.post("/auth/login")
async def admin_login(
    body: AdminLoginReq,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """管理员密码登录（httpOnly cookie 会话）。

    频控两把锁（方案 §8.4）：用户名级 5/5min + 真实 IP 级 20/5min。
    """
    await check_code_rate_limit(
        f"admin:login:user:{body.username}", max_count=5, window=300
    )
    ip = get_real_client_ip(request)
    await check_code_rate_limit(f"admin:login:ip:{ip}", max_count=20, window=300)

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalars().first()

    # 统一 401：不区分"用户不存在"与"密码错"，避免枚举账号
    if not user or not await verifypwd(body.password, user.hashed_password):
        return resp_json(CommonErr.FORBIDDEN, detail="用户名或密码错误")

    if user.account_level != "admin":
        return resp_json(CommonErr.FORBIDDEN, detail="无后台访问权限")

    if user.is_locked and user.locked_until and user.locked_until > now_iso():
        return resp_json(CommonErr.FORBIDDEN, detail="账号已锁定")

    # 会话体在 commit 前快照（避免 commit 后 expire 引发的异步重载）
    access_token = create_admin_access_token(user)  # 读 user.id/account_level（已加载）
    payload = _admin_user_payload(user)  # 读 created_at 等（已加载）

    # 组织 refresh：本骨架复用现有 RefreshToken 表存哈希，暂不区分 kind（见下方注释）
    raw_refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            kind="admin",
            mfa_verified=False,
            expires_at=now_iso() + datetime.timedelta(days=REFRESH_TOKEN_DAYS),
            revoked_at=None,
        )
    )
    await db.commit()

    # cookie 设置在最终返回的 JSONResponse 上（注入的 response 会被丢弃，见文件头注释）
    resp = resp_json(CommonErr.OK, data=payload)
    _set_access_cookie(resp, access_token)
    _set_refresh_cookie(resp, raw_refresh)
    return resp


@router.post("/auth/refresh")
async def admin_refresh(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """用 refresh cookie 换新 access + 旋转新 refresh。

    consume_once 原子撤销：并发下同一 refresh 只能被消费一次（复用检测）。
    """
    await check_code_rate_limit("admin:token:refresh:global", max_count=30, window=60)

    raw_refresh = request.cookies.get(REFRESH_NAME)
    if not raw_refresh:
        return resp_json(CommonErr.FORBIDDEN, detail="缺少刷新令牌")

    tok_hash = hash_refresh_token(raw_refresh)
    now = now_iso()
    if not await consume_once(
        db,
        RefreshToken,
        {"revoked_at": now},
        RefreshToken.token_hash == tok_hash,
        RefreshToken.kind == "admin",
        RefreshToken.revoked_at.is_(None),
    ):
        return resp_json(CommonErr.FORBIDDEN, detail="刷新令牌无效")

    stored = await get_or_raise(
        db,
        RefreshToken,
        AuthErr.TOKEN_INVALID,
        RefreshToken.token_hash == tok_hash,
    )
    if stored.expires_at <= now:
        return resp_json(CommonErr.FORBIDDEN, detail="会话已过期")

    user = await get_or_raise(
        db,
        User,
        AuthErr.USER_NOT_FOUND,
        User.id == stored.user_id,
    )
    if user.account_level != "admin":
        return resp_json(CommonErr.FORBIDDEN, detail="会话无效")

    # 会话体在 commit 前快照（避免 commit 后 expire 引发异步重载）
    access_token = create_admin_access_token(user)
    payload = _admin_user_payload(user)

    new_refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_refresh),
            kind="admin",
            mfa_verified=False,
            expires_at=now_iso() + datetime.timedelta(days=REFRESH_TOKEN_DAYS),
            revoked_at=None,
        )
    )
    await db.commit()

    resp = resp_json(CommonErr.OK, data=payload)
    _set_access_cookie(resp, access_token)
    _set_refresh_cookie(resp, new_refresh)
    return resp


@router.post("/auth/logout")
async def admin_logout(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """登出：撤销对应 refresh 令牌并清空 cookie。"""
    raw_refresh = request.cookies.get(REFRESH_NAME)
    if raw_refresh:
        tok_hash = hash_refresh_token(raw_refresh)
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == tok_hash,
                RefreshToken.kind == "admin",
            )
        )
        stored = result.scalars().first()
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = now_iso()
            await db.commit()
    resp = resp_json(CommonErr.OK, data={"ok": True})
    _clear_cookies(resp)
    return resp


@router.get("/auth/me")
@respond
async def admin_me(cur: CurrentUser = require_admin) -> dict[str, int | str]:
    """当前后台登录态（需有效 admin access cookie），供前端 bootAdminSession 使用。"""
    return {
        "id": cur.id,
        "account_level": cur.account_level,
        "role": cur.role,
    }
