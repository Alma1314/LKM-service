"""Passkey（WebAuthn）服务 —— 注册、登录、凭证管理。

WebAuthn 协议与密码学验证（COSE key、authenticatorData、ECDSA/RSA 签名、
sign-count 回拨检测、origin/rpIdHash/signature 校验）统一交给官方库
``webauthn``（Duwab）处理，本模块只负责：挑战码的持久化/一次性消费、
options 的生成与前后端字段透传、以及凭证的数据库存取。
"""

import asyncio
import base64
import json
import logging
import os
import secrets
from typing import Any

from sqlalchemy import delete as sa_delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.core.err import BizError
from app.modules.auth.errors import AuthErr
from app.db.models import User, expires_at, now_iso
from app.db.repo import consume_once, get_or_raise
from app.db.session import new_session
from app.modules.auth.models import PasskeyChallenge, PasskeyCredential
from app.modules.auth.service_auth import finalize_auth_response

_CHALLENGE_TTL_MINUTES = 5

# 注册/advertise 的签名算法：与 create 端 pubKeyCredParams 保持一致
_SUPPORTED_PUB_KEY_ALGS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
]

_log = logging.getLogger("passkey.cleanup")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s)


async def _store_challenge(db: AsyncSession) -> tuple[str, str]:
    """将 WebAuthn 挑战码持久化到数据库（跨 worker 共享，过期自动失效）。"""
    challenge_id = secrets.token_hex(16)
    challenge = _b64(os.urandom(32))
    expiry = expires_at(minutes=_CHALLENGE_TTL_MINUTES)
    db.add(PasskeyChallenge(
        challenge_id=challenge_id,
        challenge=challenge,
        expires_at=expiry,
    ))
    await db.flush()
    return challenge_id, challenge


async def _consume_challenge(db: AsyncSession, challenge_id: str) -> bytes:
    """原子地消费挑战码 —— 使用条件 UPDATE 防止重放。返回挑战码字节（供官方库 expected_challenge）。"""
    now = now_iso()
    if not await consume_once(
        db,
        PasskeyChallenge,
        {"consumed": True},
        PasskeyChallenge.challenge_id == challenge_id,
        PasskeyChallenge.consumed.is_(False),
        PasskeyChallenge.expires_at > now,
    ):
        return b""
    row = (
        await db.execute(select(PasskeyChallenge).where(PasskeyChallenge.challenge_id == challenge_id))
    ).scalars().first()
    return _b64decode(str(row.challenge)) if row else b""


_CLEANUP_INTERVAL_SECONDS = 300  # 5 分钟


async def cleanup_expired_challenges() -> None:
    """后台任务：定期清理已过期或已被消费的挑战码。"""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            db = await new_session()
            try:
                now = now_iso()
                result = await db.execute(
                    sa_delete(PasskeyChallenge).where(
                        or_(PasskeyChallenge.consumed.is_(True), PasskeyChallenge.expires_at <= now)
                    )
                )
                await db.commit()
                deleted = int(result.rowcount) if result.rowcount else 0  # type: ignore[union-attr]
                if deleted:
                    _log.info("Cleaned up %d expired/consumed passkey challenges", deleted)
            except (OSError, RuntimeError):
                await db.rollback()
                _log.exception("Failed to clean up expired passkey challenges")
            finally:
                await db.close()
        except Exception:  # noqa: BLE001
            _log.exception("cleanup_expired_challenges: unexpected error outside DB session")


async def begin_passkey_registration(db: AsyncSession, user_id: int) -> dict[str, Any]:
    user = await get_or_raise(db, User, AuthErr.USER_NOT_FOUND, User.id == user_id)

    challenge_id, challenge_b64 = await _store_challenge(db)
    user_handle = user_id.to_bytes(8, "big")

    existing = (
        await db.execute(select(PasskeyCredential).where(PasskeyCredential.user_id == user_id))
    ).scalars().all()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=_b64decode(c.credential_id))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=user_handle,
        user_name=user.username,
        user_display_name=user.username,
        challenge=_b64decode(challenge_b64),
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        attestation=AttestationConveyancePreference.NONE,
        exclude_credentials=exclude_credentials,
        supported_pub_key_algs=_SUPPORTED_PUB_KEY_ALGS,
    )
    return {
        "challenge_id": challenge_id,
        "public_key": json.loads(options_to_json(options)),
    }


def _registration_credential(credential: dict[str, Any]) -> dict[str, Any]:
    """把前端 payload 组装成官方库 verify_registration_response 需要的 credential 字典。

    前端只回传 rawId + response{clientDataJSON, attestationObject}；官方库还要求
    ``id`` 与 ``type``，这里补上。rawId 本身即 base64url 的凭证 id。
    """
    raw_id: str | None = credential.get("rawId")
    response: dict[str, Any] = credential.get("response", {})
    if not raw_id or not response.get("clientDataJSON") or not response.get("attestationObject"):
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "rawId and attestationObject required")
    return {
        "id": raw_id,
        "rawId": raw_id,
        "type": PublicKeyCredentialType.PUBLIC_KEY.value,
        "response": response,
    }


async def complete_passkey_registration(
    db: AsyncSession, user_id: int, credential: dict[str, Any]
) -> dict[str, Any]:
    challenge_id: str | None = credential.get("challenge_id")
    if not challenge_id:
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "challenge_id required")

    expected_challenge = await _consume_challenge(db, challenge_id)
    if not expected_challenge:
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "Challenge expired or invalid")

    try:
        verified = verify_registration_response(
            credential=_registration_credential(credential),
            expected_challenge=expected_challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.origin,
            supported_pub_key_algs=_SUPPORTED_PUB_KEY_ALGS,
        )
    except WebAuthnException as exc:
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "Invalid attestation") from exc

    raw_id: str | None = credential.get("rawId")
    if not raw_id:
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "rawId required")
    existing = (
        await db.execute(select(PasskeyCredential).where(PasskeyCredential.credential_id == raw_id))
    ).scalars().first()
    if existing:
        raise BizError(AuthErr.PASSKEY_REGISTRATION_FAILED, "Credential already registered")

    device_name = credential.get("device_name", "Unknown device")

    cred = PasskeyCredential(
        user_id=user_id,
        credential_id=raw_id,
        public_key=_b64(verified.credential_public_key),
        sign_count=verified.sign_count,
        device_name=device_name,
    )
    db.add(cred)

    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if user and str(user.account_level) == "local":
        await db.flush()
    return {"message": "Passkey registered successfully", "device_name": device_name}


async def begin_passkey_login(db: AsyncSession) -> dict[str, Any]:
    challenge_id, challenge_b64 = await _store_challenge(db)

    options = generate_authentication_options(
        rp_id=settings.rp_id,
        challenge=_b64decode(challenge_b64),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {
        "challenge_id": challenge_id,
        "public_key": json.loads(options_to_json(options)),
    }


def _signature_raw_to_der(signature_bytes: bytes) -> bytes:
    """把 WebAuthn 原始的 64 字节 ECDSA 签名 (r||s) 转成 DER。

    浏览器返回的 ECDSA 签名是原始 r||s；而 DuWab 2.7 的 verify_signature 对 EC2
    直接交给 cryptography 的 ``verify``（默认期望 DER）。这里转成 DER，保证与
    真实浏览器签名的兼容。非 64 字节（如 RSA/Ed25519）原样返回。
    """
    if len(signature_bytes) == 64:
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        r = int.from_bytes(signature_bytes[:32], "big")
        s_ints = int.from_bytes(signature_bytes[32:], "big")
        return encode_dss_signature(r, s_ints)
    return signature_bytes


def _authentication_credential(credential: dict[str, Any]) -> dict[str, Any]:
    """把前端 payload 组装成官方库 verify_authentication_response 需要的 credential 字典。"""
    raw_id: str | None = credential.get("rawId")
    response: dict[str, Any] = credential.get("response", {})
    if not raw_id or not response.get("clientDataJSON") or not response.get("authenticatorData") or not response.get("signature"):
        raise BizError(AuthErr.PASSKEY_VERIFICATION_FAILED, "rawId, authenticatorData and signature required")
    out: dict[str, Any] = {
        "id": raw_id,
        "rawId": raw_id,
        "type": PublicKeyCredentialType.PUBLIC_KEY.value,
        "response": dict(response),
    }
    if response.get("userHandle"):
        out["response"]["userHandle"] = response["userHandle"]
    # 浏览器原始签名是 r||s；库期望 DER，先转换
    raw_sig = _b64decode(str(response["signature"]))
    out["response"]["signature"] = _b64(_signature_raw_to_der(raw_sig))
    return out


async def complete_passkey_login(db: AsyncSession, credential: dict[str, Any]) -> dict[str, Any]:
    challenge_id: str | None = credential.get("challenge_id")
    if not challenge_id:
        raise BizError(AuthErr.PASSKEY_VERIFICATION_FAILED, "challenge_id required")

    expected_challenge = await _consume_challenge(db, challenge_id)
    if not expected_challenge:
        raise BizError(AuthErr.PASSKEY_VERIFICATION_FAILED, "Challenge expired or invalid")

    raw_id: str | None = credential.get("rawId")
    if not raw_id:
        raise BizError(AuthErr.PASSKEY_VERIFICATION_FAILED, "rawId required")
    passkey = await get_or_raise(
        db, PasskeyCredential, AuthErr.PASSKEY_VERIFICATION_FAILED,
        PasskeyCredential.credential_id == raw_id,
        detail="Credential not found",
    )

    # official 库包 origin/challenge/rpIdHash/user_presence + signature，
    # 内置 sign-count 回拨检测（响应计数 <= 当前计数会被拒绝）
    try:
        verified = verify_authentication_response(
            credential=_authentication_credential(credential),
            expected_challenge=expected_challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.origin,
            credential_public_key=_b64decode(str(passkey.public_key)),
            credential_current_sign_count=passkey.sign_count,
        )
    except WebAuthnException as exc:
        raise BizError(AuthErr.PASSKEY_VERIFICATION_FAILED, "Invalid signature") from exc

    passkey.sign_count = verified.new_sign_count
    await db.flush()

    user = await get_or_raise(
        db, User, AuthErr.USER_NOT_FOUND, User.id == passkey.user_id,
        options=(selectinload(User.profile),),
    )

    if user.account_level == "local":
        raise BizError(AuthErr.ACCOUNT_LEVEL_INSUFFICIENT)

    return await finalize_auth_response(db, user)


async def list_credentials(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    creds = (
        await db.execute(select(PasskeyCredential).where(PasskeyCredential.user_id == user_id))
    ).scalars().all()
    return [
        {
            "id": c.id,
            "credential_id": c.credential_id,
            "device_name": c.device_name,
            "created_at": c.created_at,
        }
        for c in creds
    ]


async def delete_credential(db: AsyncSession, user_id: int, credential_id: int) -> dict[str, Any]:
    cred = await get_or_raise(
        db, PasskeyCredential, AuthErr.PASSKEY_VERIFICATION_FAILED,
        PasskeyCredential.id == credential_id,
        PasskeyCredential.user_id == user_id,
        detail="Credential not found",
    )
    await db.delete(cred)
    await db.flush()
    return {"message": "Credential deleted"}
