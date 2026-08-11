import base64
import binascii
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Any, cast
from urllib.parse import quote

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.config import settings
from app.core.err import BizError

_ALGORITHM = "pbkdf2:sha256"
_ITERATIONS = 600_000
_HASH_FN = "sha256"


def hashpwd(raw: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{_ALGORITHM}${salt}${hashed}"


def verifypwd(raw: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) == 3:
            algo, salt, hashed = parts
            _ = algo
        elif len(parts) == 2:
            salt, hashed = parts
        else:
            return False
    except (ValueError, AttributeError):
        return False
    nhash = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return hmac.compare_digest(nhash, hashed)

_ACCESS_TYPE = "access"
_TEMP_TYPE = "temp"

# JWT audience：区分三套互不混用的令牌，防止 token 被误喂给其他端点
_AUD_WEB = "lkm:web"      # 前台 Bearer access
_AUD_TEMP = "lkm:temp"    # 一次性 temp（2FA/recovery/setup）
_AUD_ADMIN = "lkm:admin"  # 后台 access cookie


def create_access_token(
    user_id: object,
    account_level: object,
    role: object,
    trust_device: bool = False,
    token_version: object = 0,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "user_id": int(user_id),  # type: ignore[arg-type]
        "account_level": str(account_level),
        "role": str(role),
        "trust_device": trust_device,
        "type": _ACCESS_TYPE,
        "token_version": int(token_version),  # type: ignore[arg-type]
        "aud": _AUD_WEB,
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    payload = cast(
        dict[str, Any],
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], audience=_AUD_WEB),
    )
    if payload.get("type") != _ACCESS_TYPE:
        raise ValueError("non-access token")
    return payload

_TEMP_EXPIRE_SECONDS = 60


def create_temp_token(user_id: int, purpose: str = "2fa", txn_id: str | None = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "user_id": user_id,
        "type": _TEMP_TYPE,
        "purpose": purpose,
        "aud": _AUD_TEMP,
        "iat": now,
        "exp": now + _TEMP_EXPIRE_SECONDS,
    }
    if txn_id:
        payload["txn_id"] = txn_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_temp_token(token: str) -> dict[str, Any]:
    payload = cast(
        dict[str, Any],
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], audience=_AUD_TEMP),
    )
    if payload.get("type") != _TEMP_TYPE:
        raise ValueError("non-temp token")
    return payload

_TOTP_DIGITS = 6
_TOTP_STEP = 30


def generate_totp_secret() -> str:
    raw = os.urandom(20)
    return base64.b32encode(raw).decode("ascii")


def get_totp_uri(secret: str, username: str, issuer: str) -> str:
    label = quote(f"{issuer}:{username}")
    params = f"secret={quote(secret)}&issuer={quote(issuer)}&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_STEP}"
    return f"otpauth://totp/{label}?{params}"


def _totp_now() -> int:
    return int(time.time()) // _TOTP_STEP


def _totp_code(key: bytes, counter: int) -> str:
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    raw = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{raw % 1_000_000:0{_TOTP_DIGITS}d}"


def verify_totp(secret: str, code: str, window: int = 1) -> int | None:
    try:
        key = base64.b32decode(secret, casefold=True)
    except (binascii.Error, ValueError):
        return None
    now = _totp_now()
    for step in range(now - window, now + window + 1):
        if _totp_code(key, step) == code:
            return step
    return None

_RECOVERY_CODE_BYTES = 10  # 20 hex chars


def generate_recovery_codes(n: int = 10) -> list[tuple[str, str]]:
    codes: list[tuple[str, str]] = []
    for _ in range(n):
        plain = secrets.token_hex(_RECOVERY_CODE_BYTES)
        hashed = hashlib.sha256(plain.encode()).hexdigest()
        codes.append((plain, hashed))
    return codes

def _derive_key() -> bytes:
    """32-byte AES-256 key from SHA-256."""
    return hashlib.sha256(settings.totp_encryption_key.encode()).digest()


def encrypt_secret(plain: str) -> str:
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plain.encode(), None)
    # store nonce || ciphertext
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    """base64-encoded AES-GCM"""
    key = _derive_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(cipher)
    nonce = raw[:12]
    ct = raw[12:]
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
