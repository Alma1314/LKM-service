"""设置路由 -- 邮箱 / 手机号绑定端点。

所有端点都需要已登录用户（get_current_user）。

POST /auth/settings/bind-email/request  {email}  -> 通过 EmailProvider 发送验证码
POST /auth/settings/bind-email/verify   {email, code} -> 绑定 + 如果是本地用户则升级
POST /auth/settings/bind-phone/request  {phone}  -> 通过 SmsProvider 发送验证码
POST /auth/settings/bind-phone/verify   {phone, code} -> 绑定 + 如果是本地用户则升级
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode, respond
from app.db.models import User
from app.db.repo import get_or_raise
from app.db.session import get_session
from app.modules.auth import service_2fa, service_auth
from app.modules.auth.deps import (
    CurrentUser,
    get_current_user,
    get_email_provider,
    get_sms_provider,
)
from app.modules.auth.models import TOTP, UserOAuth
from app.modules.auth.providers.base import EmailProvider, SmsProvider
from app.modules.auth.schemas import (
    BindCodeRequestResponse,
    BindCodeVerifyResponse,
    MessageResponse,
    SettingsInfo,
    UnbindRequest,
)
from app.modules.auth.service_verify import (
    check_code_rate_limit,
    consume_email_code,
    consume_phone_code,
    create_email_verification,
    create_phone_verification,
)
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth/settings", tags=["auth-settings"])

_BIND_PURPOSE = "bind"

class BindEmailRequest(BaseModel):
    email: EmailStr


class BindEmailVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class BindPhoneRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)


class BindPhoneVerify(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)
    code: str = Field(..., min_length=6, max_length=6)

@router.post("/bind-email/request", response_model=ApiResp[BindCodeRequestResponse])
@respond
def bind_email_request(
    body: BindEmailRequest,
    background_tasks: BackgroundTasks,
    _cur: CurrentUser = Depends(get_current_user),
    email_provider: EmailProvider = Depends(get_email_provider),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """请求用于绑定的邮箱验证码。"""
    # 检查邮箱是否已被占用
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED, "Email already bound to another account")

    rate_limit_key = f"bind_email:{body.email}"
    check_code_rate_limit(rate_limit_key)

    code, record_id = create_email_verification(db, body.email, _BIND_PURPOSE)
    background_tasks.add_task(email_provider.send_code, body.email, code)

    return {"message": "Verification code sent to email", "record_id": record_id}


@router.post("/bind-email/verify", response_model=ApiResp[BindCodeVerifyResponse])
@respond
def bind_email_verify(
    body: BindEmailVerify,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """验证邮箱验证码并将邮箱绑定到当前用户。"""
    consume_email_code(db, body.email, body.code, _BIND_PURPOSE)

    # 确保邮箱仍未被占用（可能在请求和验证之间被占用）
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED, "Email already bound to another account")

    user = get_or_raise(db, User, ErrCode.USER_NOT_FOUND, User.id == cur.id)

    user.email = body.email
    db.flush()

    # 如果适用，将本地用户升级为普通用户
    service_auth.upgrade_to_normal(db, user) # type: ignore[arg-type]

    return {"message": "Email bound successfully"}

@router.post("/bind-phone/request", response_model=ApiResp[BindCodeRequestResponse])
@respond
def bind_phone_request(
    body: BindPhoneRequest,
    background_tasks: BackgroundTasks,
    _cur: CurrentUser = Depends(get_current_user),
    sms_provider: SmsProvider = Depends(get_sms_provider),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """请求用于绑定的短信验证码。"""
    # 检查手机号是否已被占用
    existing = db.query(User).filter(User.phone == body.phone).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED, "Phone already bound to another account")

    rate_limit_key = f"bind_phone:{body.phone}"
    check_code_rate_limit(rate_limit_key)

    code, record_id = create_phone_verification(db, body.phone, _BIND_PURPOSE)
    background_tasks.add_task(sms_provider.send_code, body.phone, code)

    return {"message": "Verification code sent to phone", "record_id": record_id}


@router.post("/bind-phone/verify", response_model=ApiResp[BindCodeVerifyResponse])
@respond
def bind_phone_verify(
    body: BindPhoneVerify,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """验证手机验证码并将手机号绑定到当前用户。"""
    consume_phone_code(db, body.phone, body.code, _BIND_PURPOSE)

    # 确保手机号仍未被占用
    existing = db.query(User).filter(User.phone == body.phone).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED, "Phone already bound to another account")

    user = get_or_raise(db, User, ErrCode.USER_NOT_FOUND, User.id == cur.id)

    user.phone = body.phone
    db.flush()

    # 如果适用，将本地用户升级为普通用户
    service_auth.upgrade_to_normal(db, user) # type: ignore[arg-type]

    return {"message": "Phone bound successfully"}


@router.get("", response_model=ApiResp[SettingsInfo])
@respond
def get_settings(
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """返回当前用户的绑定状态（邮箱 / 手机号 / GitHub / 2FA）。"""
    user = get_or_raise(db, User, ErrCode.USER_NOT_FOUND, User.id == cur.id)
    gh = (
        db.query(UserOAuth)
        .filter(UserOAuth.user_id == cur.id, UserOAuth.provider == "github")
        .first()
    )
    totp = db.query(TOTP).filter(TOTP.user_id == cur.id, TOTP.enabled.is_(True)).first()
    return {
        "email": user.email or None,
        "phone": user.phone or None,
        "github": gh.provider_email if gh else None,
        "has_2fa": totp is not None,
    }


_ALLOWED_UNBIND = {"email", "phone", "github"}


@router.delete("/{binding_type}", response_model=ApiResp[MessageResponse])
@respond
def unbind(
    binding_type: str,
    body: UnbindRequest,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """解绑邮箱 / 手机号 / GitHub。已开启 2FA 时需携带 TOTP 码二次验证。"""
    if binding_type not in _ALLOWED_UNBIND:
        raise BizError(ErrCode.INVALID_INPUT, f"Unsupported binding type: {binding_type}")

    user = get_or_raise(db, User, ErrCode.USER_NOT_FOUND, User.id == cur.id)

    if binding_type in ("email", "phone"):
        # 2FA 门槛：已开启 2FA 必须带 TOTP 码
        totp = db.query(TOTP).filter(TOTP.user_id == cur.id, TOTP.enabled.is_(True)).first()
        if totp is not None:
            if not body.code:
                raise BizError(ErrCode.TOTP_CODE_INVALID, "2FA 已开启，解绑需要动态验证码")
            service_2fa.verify_user_totp(db, cur.id, body.code)

        # 保留至少一种登录方式：normal 用户要求 email/phone/github 至少留一个
        if _count_login_ways(user) <= 1:
            raise BizError(ErrCode.INVALID_INPUT, "至少需要保留一种登录方式（邮箱/手机号/GitHub）")

        if binding_type == "email":
            user.email = None
        else:
            user.phone = None
        db.flush()
        return {"message": f"{binding_type} unbound"}

    # github
    deleted = (
        db.query(UserOAuth)
        .filter(UserOAuth.user_id == cur.id, UserOAuth.provider == "github")
        .delete()
    )
    db.flush()
    if not deleted:
        raise BizError(ErrCode.INVALID_INPUT, "GitHub 尚未绑定")
    return {"message": "github unbound"}


def _count_login_ways(user: User) -> int:
    count = 0
    if user.email:
        count += 1
    if user.phone:
        count += 1
    if user.oauth_bindings:
        count += 1
    return count
