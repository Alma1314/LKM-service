"""
2FA (TOTP) HTTP 端点。
POST   /auth/2fa/setup/begin     RequireLevel("normal")  开始 TOTP 设置
POST   /auth/2fa/setup/temp      temp_token 认证         开始 TOTP 设置（管理员强制设置）
POST   /auth/2fa/setup/complete  RequireLevel("normal")  完成 TOTP 设置
POST   /auth/2fa/verify          public (temp_token)     登录时验证 2FA
DELETE /auth/2fa                  RequireLevel("normal")  禁用 2FA
"""

import hashlib
from typing import Any, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, respond
from app.modules.auth.errors import AuthErr
from app.db.models import User, expires_at, now_iso
from app.db.repo import consume_once
from app.db.session import get_session
from app.modules.auth import security, service_2fa
from app.modules.auth.deps import CurrentUser, RequireLevel
from app.modules.auth.models import SetupTransaction, TOTP
from app.modules.auth.schemas import (
    TOTPConfirmResponse,
    TOTPDisableRequest,
    TOTPDisableResponse,
    TOTPSetupBeginData,
    TOTPSetupCompleteData,
    TOTPSetupCompleteRequest,
    TOTPSetupCompleteTempData,
    TOTPStatusData,
    TOTPVerifyRequest,
    TOTPVerifyResponse,
)
from app.modules.auth.service_auth import _generate_refresh_token, _store_refresh_token
from app.modules.auth.service_verify import check_code_rate_limit
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth/2fa", tags=["auth-2fa"])


def _decode_setup_temp_token(temp_token: str) -> tuple[str, int]:
    """解码并验证 setup 临时令牌，返回 (token_hash, user_id)。"""
    try:
        payload = cast(
            dict[str, Any],
            security.decode_temp_token(temp_token),  # type: ignore[reportUnknownMemberType]
        )
    except Exception as exc:
        raise BizError(AuthErr.TOKEN_INVALID) from exc
    if payload.get("purpose") != "setup":
        raise BizError(AuthErr.TOKEN_INVALID, "Not a setup token")
    user_id = payload.get("user_id")
    if not user_id:
        raise BizError(AuthErr.TOKEN_INVALID)
    token_hash = hashlib.sha256(temp_token.encode()).hexdigest()
    return token_hash, user_id  # type: ignore[arg-type]


@router.post("/setup/begin", response_model=ApiResp[TOTPSetupBeginData])
@respond
async def setup_2fa_begin(
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """开始 TOTP 设置。返回密钥和二维码 URI。"""
    result = cast(
        dict[str, Any],
        await service_2fa.setup_2fa_begin(db, cur.id),  # type: ignore[reportUnknownMemberType]
    )
    return result


@router.post("/setup/temp", response_model=ApiResp[TOTPSetupBeginData])
@respond
async def setup_2fa_temp(
    temp_token: str,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """使用登录时获得的临时令牌开始 TOTP 设置（管理员强制设置）。"""
    token_hash, user_id = _decode_setup_temp_token(temp_token)

    # 原子性地声明设置令牌 — 只有一个 begin 调用会成功
    try:
        db.add(SetupTransaction(
            token_hash=token_hash,
            user_id=user_id,
            consumed=False,
            expires_at=expires_at(minutes=10),
        ))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BizError(AuthErr.TOKEN_INVALID, "Setup token already used")

    return cast(
        dict[str, Any],
        await service_2fa.setup_2fa_begin(db, user_id),  # type: ignore[reportUnknownMemberType]
    )


@router.post("/setup/complete/temp", response_model=ApiResp[TOTPSetupCompleteTempData])
@respond
async def setup_2fa_complete_temp(
    temp_token: str,
    code: str,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """使用临时令牌完成 TOTP 设置（管理员强制设置路径）。"""
    token_hash, user_id = _decode_setup_temp_token(temp_token)

    # 原子性地消耗设置事务
    if not await consume_once(
        db,
        SetupTransaction,
        {"consumed": True},
        SetupTransaction.token_hash == token_hash,
        SetupTransaction.consumed.is_(False),
        SetupTransaction.expires_at > now_iso(),
    ):
        raise BizError(AuthErr.TOKEN_INVALID, "Setup token not found, already used, or expired")

    txn = (await db.execute(select(SetupTransaction).where(SetupTransaction.token_hash == token_hash))).scalars().first()
    if not txn or txn.user_id != user_id:
        raise BizError(AuthErr.TOKEN_INVALID)

    result_dict = cast(
        dict[str, Any],
        await service_2fa.setup_2fa_complete(db, user_id, code),  # type: ignore[reportUnknownMemberType, arg-type]
    )
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if user:
        result_dict["access_token"], result_dict["refresh_token"] = await _issue_admin_setup_tokens(db, user)
    return result_dict


async def _issue_admin_setup_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = security.create_access_token(
        user_id=user.id,
        account_level=user.account_level,
        role="admin",
        token_version=user.token_version,
    )
    raw_refresh = _generate_refresh_token()
    await _store_refresh_token(db, user.id, raw_refresh, mfa_verified=True)
    return access_token, raw_refresh


@router.post("/setup/complete", response_model=ApiResp[TOTPSetupCompleteData])
@respond
async def setup_2fa_complete(
    body: TOTPSetupCompleteRequest,
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """通过验证 TOTP 码完成 TOTP 设置。返回恢复码。"""
    result = cast(
        dict[str, Any],
        await service_2fa.setup_2fa_complete(db, cur.id, body.code),  # type: ignore[reportUnknownMemberType]
    )
    return result


@router.post("/setup/confirm", response_model=ApiResp[TOTPConfirmResponse])
@respond
async def confirm_recovery_codes(
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """确认用户已保存其恢复码。"""
    return cast(
        dict[str, Any],
        await service_2fa.confirm_recovery_codes_saved(db, cur.id),  # type: ignore[reportUnknownMemberType]
    )


@router.post("/verify", response_model=ApiResp[TOTPVerifyResponse])
@respond
async def verify_2fa(
    body: TOTPVerifyRequest,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """在登录时使用临时令牌和 TOTP / 恢复码验证 2FA。"""
    check_code_rate_limit("2fa:verify:global", max_count=10, window=3600)
    result = cast(
        dict[str, Any],
        await service_2fa.verify_2fa(  # type: ignore[reportUnknownMemberType]
            db,
            temp_token=body.temp_token,
            code=body.code,
            recovery_code=body.recovery_code,
            trust_device=body.trust_device,
        ),
    )
    return result


@router.delete("", response_model=ApiResp[TOTPDisableResponse])
@respond
async def disable_2fa(
    body: TOTPDisableRequest,
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
):
    """为当前用户禁用 2FA。需要有效的 TOTP 码。"""
    result = cast(
        dict[str, Any],
        await service_2fa.disable_2fa(db, cur.id, body.code),  # type: ignore[reportUnknownMemberType]
    )
    return result


@router.get("/status", response_model=ApiResp[TOTPStatusData])
@respond
async def get_2fa_status(
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
):
    """返回当前用户 2FA 是否已开启。"""
    totp = (
        await db.execute(select(TOTP).where(TOTP.user_id == cur.id, TOTP.enabled.is_(True)))
    ).scalars().first()
    return {"enabled": totp is not None}
