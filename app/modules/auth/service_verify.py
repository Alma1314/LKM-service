"""验证码服务：生成、哈希、创建、消费、速率限制。"""

import datetime
import hashlib
import hmac
import secrets

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.err import BizError, ErrCode
from app.core.throttle import RateLimiter
from app.db.models import now_iso
from app.modules.auth.models import EmailVerification, PhoneVerification

_CODE_EXPIRE_MINUTES = 10
_MAX_FAILED_ATTEMPTS = 3

_rate_limiter = RateLimiter()

def generate_code() -> str:
    """返回一个 6 位数字验证码，格式为零填充字符串。"""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(raw: str, purpose: str = "", contact: str = "", nonce: str = "") -> str:
    import hmac
    from app.core.config import settings
    pepper = settings.verification_code_pepper.encode()
    msg = f"{raw}:{purpose}:{contact}:{nonce}".encode("utf-8")
    return hmac.new(pepper, msg, hashlib.sha256).hexdigest()

def create_email_verification(
    db, email: str, purpose: str
) -> tuple[str, int]:
    """创建一个 EmailVerification 记录并返回 (明文验证码, 记录ID)。"""
    code = generate_code()
    expires_at = _expires_at()
    nonce = secrets.token_hex(8)
    record = EmailVerification(
        email=email,
        code_hash=hash_code(code, purpose, contact=email, nonce=nonce),
        nonce=nonce,
        purpose=purpose,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return code, record.id


def create_phone_verification(
    db, phone: str, purpose: str
) -> tuple[str, int]:
    """创建一个 PhoneVerification 记录并返回 (明文验证码, 记录ID)。"""
    code = generate_code()
    expires_at = _expires_at()
    nonce = secrets.token_hex(8)
    record = PhoneVerification(
        phone=phone,
        code_hash=hash_code(code, purpose, contact=phone, nonce=nonce),
        nonce=nonce,
        purpose=purpose,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return code, record.id

def consume_email_code(
    db, email: str, code: str, purpose: str
) -> bool:
    """验证并消费最新匹配的 EmailVerification。"""
    record = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email == email,
            EmailVerification.purpose == purpose,
            EmailVerification.used.is_(False),
        )
        .order_by(EmailVerification.created_at.desc())
        .first()
    )
    return _consume(db, record, code)


def consume_phone_code(
    db, phone: str, code: str, purpose: str
) -> bool:
    """验证并消费最新匹配的 PhoneVerification。"""
    record = (
        db.query(PhoneVerification)
        .filter(
            PhoneVerification.phone == phone,
            PhoneVerification.purpose == purpose,
            PhoneVerification.used.is_(False),
        )
        .order_by(PhoneVerification.created_at.desc())
        .first()
    )
    return _consume(db, record, code)


def _consume(db, record, code: str) -> bool:
    if record is None:
        raise BizError(ErrCode.VERIFICATION_CODE_INVALID)

    now = now_iso()

    # 过期检查
    if datetime.datetime.fromisoformat(record.expires_at) <= datetime.datetime.fromisoformat(now):
        raise BizError(ErrCode.VERIFICATION_CODE_EXPIRED)

    # 失败尝试次数过多
    if record.failed_attempts >= _MAX_FAILED_ATTEMPTS:
        raise BizError(ErrCode.VERIFICATION_CODE_INVALID)

    # 验证码不匹配 —— 通过子事务（保存点）递增计数器，
    contact = getattr(record, "email", None) or getattr(record, "phone", "")
    if not hmac.compare_digest(record.code_hash, hash_code(code, record.purpose, contact=contact, nonce=record.nonce)):
        record_cls = type(record)
        sp = db.begin_nested()
        try:
            db.execute(
                sa_update(record_cls)
                .where(record_cls.id == record.id)
                .values(failed_attempts=record_cls.failed_attempts + 1)
            )
            db.flush()
            sp.commit()
        except (IntegrityError, OperationalError):
            sp.rollback()
        db.refresh(record)
        raise BizError(ErrCode.VERIFICATION_CODE_INVALID)

    record_cls = type(record)
    result = db.execute(
        sa_update(record_cls)
        .where(
            record_cls.id == record.id,
            record_cls.used.is_(False),
            record_cls.failed_attempts < _MAX_FAILED_ATTEMPTS,
            record_cls.expires_at > now,
        )
        .values(used=True)
    )
    if result.rowcount != 1:  # type: ignore[union-attr]
        raise BizError(ErrCode.VERIFICATION_CODE_INVALID)

    db.flush()
    return True

def check_code_rate_limit(
    key: str, max_count: int = 5, window: int = 3600
) -> None:
    """
    如果 *key* 超过了限制，则抛出 ``BizError(VERIFICATION_CODE_RATE_LIMIT)``。
    使用全局内存中的滑动窗口速率限制器。
    """
    if not _rate_limiter.check(key, max_count, window):
        raise BizError(ErrCode.VERIFICATION_CODE_RATE_LIMIT)

def _expires_at() -> str:
    return (
        datetime.datetime.fromisoformat(now_iso())
        + datetime.timedelta(minutes=_CODE_EXPIRE_MINUTES)
    ).isoformat()
