"""认证服务 —— 注册、密码登录、升级、刷新令牌。"""

import asyncio
import datetime as dt
import hashlib
import secrets

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.err import BizError, ErrCode
from app.db.models import User, Profile
from app.modules.auth.models import AuditLog, MagicLink, RefreshToken, TOTP
from app.modules.auth.schemas import (
    UserLoginPassword,
    UserRegByEmail,
    UserRegByPhone,
    UserRegLocal,
    UserRegNormal,
)
from app.modules.auth.security import (
    create_access_token,
    create_temp_token,
    hashpwd,
    verifypwd,
)
from app.modules.auth.service_verify import check_code_rate_limit
from app.modules.auth.providers.base import EmailProvider

_FAIL_LOCK_THRESHOLD = 5
_FAIL_LOCK_MINUTES = 15


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _normalize_username(username: str) -> str:
    """规范化用户名：去除空白字符并转为小写。"""
    return username.strip().lower()


def _normalize_email(email: str) -> str:
    """规范化邮箱：去除空白字符并转为小写。"""
    return email.strip().lower()


def _generate_refresh_token() -> str:
    """返回一个加密安全的随机十六进制字符串（64 个字符）。"""
    return secrets.token_hex(32)


def _hash_refresh_token(raw: str) -> str:
    """对原始刷新令牌进行 SHA-256 哈希。"""
    return hashlib.sha256(raw.encode()).hexdigest()


def _store_refresh_token(db: Session, user_id: int, raw: str, mfa_verified: bool = False) -> str:
    """持久化哈希后的刷新令牌并返回其过期时间戳字符串。"""
    days = settings.refresh_token_expire_days
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    expires_str = expires.isoformat()
    tok = RefreshToken(
        user_id=user_id,
        token_hash=_hash_refresh_token(raw),
        mfa_verified=mfa_verified,
        expires_at=expires_str,
    )
    db.add(tok)
    db.flush()
    return expires_str


def _create_auth_response(
    db: Session, user: User, requires_2fa: bool = False
) -> dict:
    """构建作为登录 / 注册响应返回的字典。"""
    profile = user.profile
    role = profile.role if profile else "member"

    if requires_2fa:
        temp_token = create_temp_token(user.id)
        return {
            "access_token": None,
            "refresh_token": None,
            "user_id": user.id,
            "account_level": user.account_level,
            "requires_2fa": True,
            "temp_token": temp_token,
        }

    access_token = create_access_token(
        user_id=user.id,
        account_level=user.account_level,
        role=role,
        token_version=user.token_version,
    )
    raw_refresh = _generate_refresh_token()
    _store_refresh_token(db, user.id, raw_refresh)

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "user_id": user.id,
        "account_level": user.account_level,
        "requires_2fa": False,
        "temp_token": None,
    }


def _check_account_locked(user: User) -> None:
    """检查用户是否被锁定 —— 但返回 INVALID_CREDENTIALS 以防止通过锁检测进行账号枚举。"""
    if not user.is_locked:
        return
    if user.locked_until:
        locked = dt.datetime.fromisoformat(user.locked_until)
        if dt.datetime.now(dt.timezone.utc) < locked:
            # 执行虚拟哈希以保持时序一致
            from app.modules.auth.security import verifypwd as _vp
            _vp("dummy", "$dummy$" + "a" * 64)
            raise BizError(ErrCode.INVALID_CREDENTIALS)
        # 锁定已过期 —— 自动解锁
        user.is_locked = False
        user.locked_until = None
        user.failed_login_attempts = 0


def _record_failed_attempt(db: Session, user: User) -> None:
    """通过子事务（保存点）递增登录失败计数器。"""

    # 在子事务中提交失败次数的递增
    sp = db.begin_nested()
    try:
        db.execute(
            text(
                "UPDATE users SET failed_login_attempts = failed_login_attempts + 1 "
                "WHERE id = :uid"
            ),
            {"uid": user.id},
        )
        db.flush()
        sp.commit()
    except Exception:
        sp.rollback()

    # 刷新 ORM 对象，使调用方能看到新值
    db.refresh(user)

    # 如果达到阈值，在另一个子事务中锁定账户
    if user.failed_login_attempts >= _FAIL_LOCK_THRESHOLD:
        locked_until = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=_FAIL_LOCK_MINUTES)
        ).isoformat()
        sp2 = db.begin_nested()
        try:
            db.execute(
                text("UPDATE users SET is_locked = 1, locked_until = :lu WHERE id = :uid"),
                {"lu": locked_until, "uid": user.id},
            )
            db.flush()
            sp2.commit()
        except Exception:
            sp2.rollback()
        db.refresh(user)

def register_local(db: Session, info: UserRegLocal) -> dict:
    """创建一个 ``local`` 账户并立即返回认证令牌。"""
    username = _normalize_username(info.username)
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED)

    user = User(
        username=username,
        hashed_password=hashpwd(info.password),
        account_level="local",
    )
    db.add(user)
    db.flush()

    db.add(Profile(user_id=user.id, role="member"))
    db.flush()

    return _create_auth_response(db, user)


def _handle_duplicate_user_error(exc: Exception) -> None:
    """如果是唯一性违规，将 IntegrityError 重新抛出为 ALREADY_REGISTERED。"""
    from sqlalchemy.exc import IntegrityError
    if isinstance(exc, IntegrityError):
        raise BizError(ErrCode.ALREADY_REGISTERED, "Account already exists") from exc
    raise


def register_normal_with_password(
    db: Session,
    info: UserRegNormal,
    email_verified: bool = False,
    phone_verified: bool = False,
) -> int:
    """创建一个带密码的 ``normal`` 账户。"""
    has_email = info.email is not None
    has_phone = info.phone is not None
    if not has_email and not has_phone:
        raise BizError(ErrCode.INVALID_INPUT, "email or phone must be provided")
    if has_email and not email_verified:
        raise BizError(ErrCode.INVALID_INPUT, "email must be verified")
    if has_phone and not phone_verified:
        raise BizError(ErrCode.INVALID_INPUT, "phone must be verified")

    username = _normalize_username(info.username)
    email_normalized = _normalize_email(info.email) if info.email else None

    existing = (
        db.query(User)
        .filter(
            (User.username == username)
            | ((User.email == email_normalized) if email_normalized else False)
            | (User.phone == info.phone)
        )
        .first()
    )
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED)

    user = User(
        username=username,
        hashed_password=hashpwd(info.password),
        email=email_normalized,
        phone=info.phone,
        account_level="normal",
    )
    db.add(user)
    db.flush()

    db.add(Profile(user_id=user.id, role="member"))
    db.flush()

    return user.id


def register_by_verify(db: Session, field: str, value: str) -> dict:
    """通过邮箱或手机验证创建一个*无密码*的普通用户。"""
    if field not in ("email", "phone"):
        raise BizError(ErrCode.INVALID_INPUT, "field must be 'email' or 'phone'")

    # 规范化并检查重复
    if field == "email":
        normalized_value = _normalize_email(value)
        existing = db.query(User).filter(User.email == normalized_value).first()
    else:
        normalized_value = value
        existing = db.query(User).filter(User.phone == normalized_value).first()

    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED)

    # 从值中派生用户名
    if field == "email":
        username = value.split("@")[0]
    else:
        username = f"user_{value[-6:]}"

    # 确保唯一性
    suffix = 1
    base = username
    while db.query(User).filter(User.username == username).first():
        username = f"{base}{suffix}"
        suffix += 1

    user = User(
        username=username,
        email=normalized_value if field == "email" else None,
        phone=value if field == "phone" else None,
        hashed_password="",
        account_level="normal",
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, role="member"))
    db.flush()

    access_token = create_access_token(user.id, user.account_level, "member", token_version=user.token_version)
    raw_refresh = _generate_refresh_token()
    _store_refresh_token(db, user.id, raw_refresh)
    log_audit(db, user.id, "register_code", f"registered via {field}")

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "user_id": user.id,
        "account_level": user.account_level,
        "requires_2fa": False,
        "temp_token": None,
    }

def _store_pending_normal_registration(
    db: Session,
    username: str,
    password: str,
    email: str | None,
    phone: str | None,
) -> str:
    from app.modules.auth.models import PendingRegistration
    import secrets as _s

    txn_id = _s.token_hex(32)
    expires_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)).isoformat()

    record = PendingRegistration(
        txn_id=txn_id,
        username=_normalize_username(username),
        hashed_password=hashpwd(password),
        email=_normalize_email(email) if email else None,
        phone=phone,
        consumed=False,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()
    return txn_id


def _consume_pending_normal_registration(
    db: Session,
    txn_id: str,
    email_code: str | None = None,
    phone_code: str | None = None,
) -> dict:
    from app.modules.auth.models import PendingRegistration
    from app.modules.auth.service_verify import consume_email_code, consume_phone_code

    pending = db.query(PendingRegistration).filter(
        PendingRegistration.txn_id == txn_id
    ).first()
    if not pending:
        raise BizError(ErrCode.TOKEN_INVALID, "Invalid registration transaction")
    if pending.consumed:
        raise BizError(ErrCode.TOKEN_INVALID, "Registration already completed")
    now = dt.datetime.now(dt.timezone.utc)
    if dt.datetime.fromisoformat(pending.expires_at) <= now:
        raise BizError(ErrCode.TOKEN_EXPIRED, "Registration expired")

    # 验证所有提交的联系方式 —— 每个提供的联系方式都必须经过验证。
    sp = db.begin_nested()
    try:
        if pending.email:
            assert email_code is not None
            consume_email_code(db, pending.email, email_code, "register")
        if pending.phone:
            assert phone_code is not None
            consume_phone_code(db, pending.phone, phone_code, "register")
        sp.commit()
    except Exception:
        sp.rollback()
        raise

    pending.consumed = True
    db.flush()

    # 检查重复
    existing = db.query(User).filter(
        (User.username == pending.username)
        | ((User.email == pending.email) if pending.email else False)
        | ((User.phone == pending.phone) if pending.phone else False)
    ).first()
    if existing:
        raise BizError(ErrCode.ALREADY_REGISTERED)

    user = User(
        username=pending.username,
        email=pending.email,
        phone=pending.phone,
        hashed_password=pending.hashed_password,
        account_level="normal",
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, role="member"))
    db.flush()

    access_token = create_access_token(user.id, user.account_level, "member", token_version=user.token_version)
    raw_refresh = _generate_refresh_token()
    _store_refresh_token(db, user.id, raw_refresh)
    log_audit(db, user.id, "register_normal", "password registration complete")

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "user_id": user.id,
        "account_level": user.account_level,
        "requires_2fa": False,
        "temp_token": None,
    }

def login_password(db: Session, info: UserLoginPassword, ip_address: str = "") -> dict:
    """通过用户名、邮箱或手机号 + 密码进行认证。"""
    from app.core.throttle import check_password_login_rate_limit
    if ip_address:
        check_password_login_rate_limit(ip_address)

    account = _normalize_username(info.account)
    email_normalized = _normalize_email(info.account)

    user = (
        db.query(User)
        .filter(
            (User.username == account)
            | (User.email == email_normalized)
            | (User.phone == info.account.strip())
        )
        .first()
    )

    if not user:
        # 防御用户枚举：执行一个相同成本的虚拟哈希，
        verifypwd(info.password, "$dummy$" + "a" * 64)
        raise BizError(ErrCode.INVALID_CREDENTIALS)

    _check_account_locked(user)

    try:
        ok = verifypwd(info.password, user.hashed_password)
    except Exception:
        ok = False
    if not ok:
        _record_failed_attempt(db, user)
        if user.failed_login_attempts >= _FAIL_LOCK_THRESHOLD:
            log_audit(db, user.id, "account_locked", "5 failed login attempts")
        raise BizError(ErrCode.INVALID_CREDENTIALS)

    # 成功 —— 通过原子 SQL 重置计数器（提交操作不受调用方回滚影响）
    db.execute(
        text(
            "UPDATE users SET failed_login_attempts = 0, is_locked = 0, "
            "locked_until = NULL WHERE id = :uid"
        ),
        {"uid": user.id},
    )
    db.flush()
    db.commit()
    db.refresh(user)

    log_audit(db, user.id, "login_password", "success")

    # 没有 TOTP 的管理员必须设置它 —— 发放一个受限的设置令牌，
    # 以便管理员可以调用 /auth/2fa/setup/begin 而不被锁定。
    if user.account_level == "admin":
        totp = db.query(TOTP).filter(TOTP.user_id == user.id).first()
        if not totp or not totp.enabled:
            setup_token = create_temp_token(user.id, purpose="setup")
            return {
                "access_token": None,
                "refresh_token": None,
                "user_id": user.id,
                "account_level": user.account_level,
                "requires_2fa": True,
                "setup_required": True,
                "temp_token": setup_token,
            }

    # 检查 2FA
    requires_2fa = False
    if user.account_level in ("normal", "admin"):
        totp = db.query(TOTP).filter(TOTP.user_id == user.id, TOTP.enabled.is_(True)).first()
        if totp:
            requires_2fa = True

    return _create_auth_response(db, user, requires_2fa=requires_2fa)


def login_code(db: Session, contact: str, code: str) -> dict:
    """使用有时效性的验证码进行认证。"""
    from app.modules.auth.service_verify import consume_email_code, consume_phone_code
    from app.modules.auth.models import TOTP

    if "@" in contact:
        consume_email_code(db, contact, code, "login")
        user = db.query(User).filter(User.email == _normalize_email(contact)).first()
    else:
        consume_phone_code(db, contact, code, "login")
        user = db.query(User).filter(User.phone == contact).first()

    if not user:
        raise BizError(ErrCode.USER_NOT_FOUND)

    if user.account_level == "local":
        raise BizError(ErrCode.ACCOUNT_LEVEL_INSUFFICIENT)

    if user.is_locked:
        _check_account_locked(user)

    # 没有 TOTP 的管理员 —— 与密码登录相同的设置流程
    if user.account_level == "admin":
        totp = db.query(TOTP).filter(TOTP.user_id == user.id).first()
        if not totp or not totp.enabled:
            setup_token = create_temp_token(user.id, purpose="setup")
            return {
                "access_token": None,
                "refresh_token": None,
                "user_id": user.id,
                "account_level": user.account_level,
                "requires_2fa": True,
                "setup_required": True,
                "temp_token": setup_token,
            }

    requires_2fa = False
    if user.account_level in ("normal", "admin"):
        totp = db.query(TOTP).filter(TOTP.user_id == user.id, TOTP.enabled.is_(True)).first()
        if totp:
            requires_2fa = True

    return _create_auth_response(db, user, requires_2fa=requires_2fa)

def request_magic_link(
    db: Session,
    email: str,
    email_provider: EmailProvider,
    purpose: str = "login",
    frontend_url: str = "",
) -> None:
    """仅在用户存在时为*邮箱*生成一个魔法链接。

    速率限制为每（邮箱, 用途）对每小时 5 次请求。
    原始令牌为 64 个十六进制字符；仅存储其 SHA-256 哈希值。

    对于不存在的用户，响应和时序无法区分
    —— 不会创建或发送链接，但仍会消耗速率限制配额。
    """
    rate_limit_key = f"magiclink:{email}"
    check_code_rate_limit(rate_limit_key, max_count=5, window=3600)

    user = db.query(User).filter(User.email == email).first()
    if not user or user.account_level == "local":
        # 无操作：不创建也不发送，但速率限制在上方已被消耗
        return

    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expires_at = (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)
    ).isoformat()

    link_record = MagicLink(
        email=email,
        token_hash=token_hash,
        purpose=purpose,
        expires_at=expires_at,
    )
    db.add(link_record)
    db.flush()

    base_url = frontend_url or settings.api_prefix
    link = f"{base_url}/auth/login/magic-link/verify?token={raw_token}"

    asyncio.create_task(email_provider.send_magic_link(email, link))


def verify_magic_link(
    db: Session,
    token: str,
    purpose: str = "login",
) -> dict:
    """
    验证魔法链接令牌并返回认证响应。
    可能抛出的异常：
        BizError(TOKEN_INVALID)  – 令牌未找到、用途不匹配或已被使用
        BizError(TOKEN_EXPIRED)  – 令牌已过期
        BizError(USER_NOT_FOUND) – 不存在与该链接邮箱关联的用户
        BizError(ACCOUNT_LEVEL_INSUFFICIENT) – 用户为 ``local`` 级别
        BizError(TOTP_SETUP_REQUIRED) – 管理员用户未启用 TOTP
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()

    # 原子消费：仅在尚未使用、未过期且用途匹配时才标记为已使用。
    # 这可防止并发重放攻击。

    result = db.execute(
        text(
            "UPDATE magic_links SET used = 1 "
            "WHERE token_hash = :hash AND used = 0 AND purpose = :purpose "
            "AND expires_at > :now"
        ),
        {"hash": token_hash, "purpose": purpose, "now": now_iso},
    )
    if result.rowcount != 1:  # pyright: ignore[reportAttributeAccessIssue]
        # 令牌可能已过期或不存在 —— 检查具体是哪一种情况
        link_record = (
            db.query(MagicLink)
            .filter(MagicLink.token_hash == token_hash)
            .first()
        )
        if not link_record:
            raise BizError(ErrCode.TOKEN_INVALID)
        if link_record.purpose != purpose:
            raise BizError(ErrCode.TOKEN_INVALID)
        if link_record.used:
            raise BizError(ErrCode.TOKEN_INVALID)
        # 必然是已过期
        raise BizError(ErrCode.TOKEN_EXPIRED)

    db.flush()

    # 原子更新后重新获取
    link_record = (
        db.query(MagicLink)
        .filter(MagicLink.token_hash == token_hash)
        .first()
    )

    if not link_record:
        raise BizError(ErrCode.TOKEN_INVALID)

    user = db.query(User).filter(User.email == link_record.email).first()
    if not user:
        raise BizError(ErrCode.USER_NOT_FOUND)

    if user.account_level == "local":
        raise BizError(ErrCode.ACCOUNT_LEVEL_INSUFFICIENT)

    # 没有 TOTP 的管理员必须设置它
    if user.account_level == "admin":
        totp = db.query(TOTP).filter(TOTP.user_id == user.id).first()
        if not totp or not totp.enabled:
            raise BizError(ErrCode.TOTP_SETUP_REQUIRED)

    # 与 login_password 相同的 2FA 检查
    requires_2fa = False
    if user.account_level in ("normal", "admin"):
        totp = db.query(TOTP).filter(TOTP.user_id == user.id, TOTP.enabled.is_(True)).first()
        if totp:
            requires_2fa = True

    return _create_auth_response(db, user, requires_2fa=requires_2fa)

def upgrade_to_normal(db: Session, user: User) -> None:
    """将 ``local`` 用户升级为 ``normal``。对于已是 normal 或 admin 的用户无操作。"""
    if user.account_level == "local":
        user.account_level = "normal"
        db.flush()
        log_audit(db, user.id, "level_change", "local -> normal")


def refresh_access_token(db: Session, raw_refresh: str) -> dict:
    tok_hash = _hash_refresh_token(raw_refresh)
    now = _now()

    # 原子撤销：仅在令牌存在且尚未被撤销时才撤销
    result = db.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = :now "
            "WHERE token_hash = :hash AND revoked_at IS NULL"
        ),
        {"now": now, "hash": tok_hash},
    )
    if result.rowcount != 1:  # pyright: ignore[reportAttributeAccessIssue]
        # 令牌已被使用、不存在或已被撤销
        raise BizError(ErrCode.TOKEN_INVALID)

    # 现在获取记录以得到 user_id 和 mfa_verified
    stored = db.query(RefreshToken).filter(
        RefreshToken.token_hash == tok_hash
    ).first()
    if not stored:
        raise BizError(ErrCode.TOKEN_INVALID)

    # 过期检查
    expires = dt.datetime.fromisoformat(stored.expires_at)
    if dt.datetime.now(dt.timezone.utc) >= expires:
        raise BizError(ErrCode.TOKEN_EXPIRED)

    # 发放新令牌
    user = db.query(User).filter(User.id == stored.user_id).first()
    if not user:
        raise BizError(ErrCode.USER_NOT_FOUND)

    # 管理员用户的刷新令牌会话必须经过 MFA 认证
    if user.account_level == "admin" and not stored.mfa_verified:
        raise BizError(ErrCode.TOKEN_INVALID, "Admin refresh token requires MFA assurance")

    profile = user.profile
    role = profile.role if profile else "member"

    access_token = create_access_token(
        user_id=user.id,
        account_level=user.account_level,
        role=role,
        token_version=user.token_version,
    )
    raw_new = _generate_refresh_token()
    _store_refresh_token(db, user.id, raw_new, mfa_verified=stored.mfa_verified)

    return {"access_token": access_token, "refresh_token": raw_new}

def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    """撤销指定用户所有未撤销的刷新令牌，并使其所有访问令牌失效。"""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": _now()}, synchronize_session="fetch")
    # 递增 token_version 以使所有现有访问令牌失效
    db.execute(
        text("UPDATE users SET token_version = token_version + 1 WHERE id = :uid"),
        {"uid": user_id},
    )
    db.flush()


def log_audit(
    db: Session,
    user_id: int | None,
    action: str,
    detail: str | None = None,
    ip_address: str | None = None,
) -> None:
    """创建一条审计日志记录。"""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
