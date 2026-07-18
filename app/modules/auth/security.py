import hashlib
import secrets

from fastapi import Header

from app.core.err import BizError, ErrCode

_ITERATIONS = 100000
_HASH_FN = "sha256"


def get_current_user_id(x_user_id: int = Header(..., alias="X-User-Id")) -> int:
    if x_user_id <= 0:
        raise BizError(ErrCode.FORBIDDEN, "Invalid user identity")
    return x_user_id


def hashpwd(raw: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{salt}${hashed}"


def verifypwd(raw: str, stored: str) -> bool:
    salt, hashed = stored.split("$", 1)
    nhash = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return nhash == hashed
