"""
后台 cookie 会话鉴权依赖。
权限单一事实源在此：能进后台 = 持有有效后台 access cookie 且 account_level == "admin"。
"""

import datetime
from typing import Any

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError, CommonErr
from app.db.models import User, now_iso
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser  # 复用其字段契约

COOKIE_NAME = "admin_session"
REFRESH_NAME = "admin_refresh"
ACCESS_TOKEN_MINUTES = 15
# 与前台/后台分离的 audience：后台 access cookie 只认本 audience，防被前台或 temp token 冒用
_ADMIN_AUD = "lkm:admin"
# cookie Path 须与浏览器发出的真实域路径一致（开发/默认 /api/v1/admin）
COOKIE_PATH = f"/{settings.api_prefix.strip('/')}/admin"


def create_admin_access_token(user: User) -> str:
    """签发后台 access token（15min）。独立 payload + type=admin + 专属 audience。
    token_version 编入 payload：改密/登出提升版本号后旧 cookie 立即失效（与前台上前台逻辑一致）。"""
    now = datetime.datetime.now(datetime.UTC)
    # payload 元素类型混杂（str/int/bool），用 object 收窄容器泛型，避免 Unknown
    payload: dict[str, object] = {
        "sub": str(user.id),
        "account_level": str(user.account_level),
        "type": "admin",
        "aud": _ADMIN_AUD,
        "token_version": int(user.token_version),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + datetime.timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_admin_access(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_ADMIN_AUD,
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.DecodeError):
        raise BizError(
            CommonErr.FORBIDDEN, "Admin session invalid or expired"
        ) from None
    if payload.get("type") != "admin":
        raise BizError(CommonErr.FORBIDDEN, "Not an admin session token")
    return payload


def _read_admin_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


async def get_current_admin(
    request: Request,
    token: str | None = Depends(_read_admin_cookie),
    db: AsyncSession = Depends(get_session),
) -> CurrentUser:
    """解析后台 access cookie → 校验 type/承载 → 查库 → 强制 account_level=admin。

    对照前台的锁定 / token_version / updated_at 校验保持一致，避免 admin 绕过前台安全态。
    """
    if not token:
        raise BizError(CommonErr.FORBIDDEN, "Not logged into admin panel")

    payload = _decode_admin_access(token)
    sub = payload.get("sub")
    if not sub:
        raise BizError(CommonErr.FORBIDDEN, "Admin session missing subject")

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise BizError(CommonErr.FORBIDDEN, "Admin session subject invalid") from None

    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.profile))
    )
    user = result.scalars().first()
    if user is None:
        raise BizError(CommonErr.FORBIDDEN, "Admin user not found")

    # 账号锁定
    if user.is_locked and user.locked_until and user.locked_until > now_iso():
        raise BizError(CommonErr.FORBIDDEN, "Admin account is locked")

    # token_version：签发时编入的版本，若已被提升（注销/改密）则当前 cookie 失效
    if int(payload.get("token_version", 0)) != int(user.token_version):
        raise BizError(CommonErr.FORBIDDEN, "Admin session invalidated")

    # 改密撤销：JWT iat 必须 >= user.updated_at（允许 5 秒时钟偏差容差），与前台一致
    if user.updated_at:
        token_iat = payload.get("iat")
        if token_iat is not None:
            token_time = datetime.datetime.fromtimestamp(
                float(token_iat), tz=datetime.UTC
            )
            if user.updated_at - token_time > datetime.timedelta(seconds=5):
                raise BizError(
                    CommonErr.FORBIDDEN, "Admin session invalidated – password changed"
                )

    # 强制管理员级别（唯一进后台门槛）
    if user.account_level != "admin":
        raise BizError(CommonErr.FORBIDDEN, "Insufficient admin privilege")

    profile = user.profile
    return CurrentUser(
        id=int(user.id),
        account_level=str(user.account_level),
        role=profile.role if profile else "member",
        email=user.email,
        phone=user.phone,
    )


require_admin = Depends(get_current_admin)


def get_real_client_ip(request: Request) -> str:
    """取客户端 IP，供后台登录 IP 级频控使用。"""
    return request.client.host if request.client else "unknown"
