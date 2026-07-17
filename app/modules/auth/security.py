import hashlib
import secrets

_ITERATIONS = 100000
_HASH_FN = "sha256"


def hashpwd(raw: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{salt}${hashed}"


def verifypwd(raw: str, stored: str) -> bool:
    salt, hashed = stored.split("$", 1)
    nhash = hashlib.pbkdf2_hmac(_HASH_FN, raw.encode(), salt.encode(), _ITERATIONS).hex()
    return nhash == hashed
