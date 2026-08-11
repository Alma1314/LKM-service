from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models import Base, now_iso, UTCDateTime

if TYPE_CHECKING:
    from app.db.models import User


class RefreshToken(Base):
    __tablename__: str = "refresh_tokens"
    __table_args__: tuple[Any, ...] = (
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # 会话用途："web"（前台 Bearer）/"admin"（后台 cookie）。用于隔离，避免跨会话互用。
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="web")
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class EmailVerification(Base):
    __tablename__: str = "email_verifications"
    __table_args__: tuple[Any, ...] = (
        Index("ix_email_verifications_lookup", "email", "purpose", "used", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    nonce: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class PhoneVerification(Base):
    __tablename__: str = "phone_verifications"
    __table_args__: tuple[Any, ...] = (
        Index("ix_phone_verifications_lookup", "phone", "purpose", "used", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    nonce: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class MagicLink(Base):
    __tablename__: str = "magic_links"
    __table_args__: tuple[Any, ...] = (
        Index("ix_magic_links_hash_purpose", "token_hash", "purpose"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class UserOAuth(Base):
    __tablename__: str = "user_oauths"
    __table_args__: tuple[Any, ...] = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    user: Mapped["User"] = relationship(back_populates="oauth_bindings")


class TOTP(Base):
    __tablename__: str = "totp"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    user: Mapped["User"] = relationship(back_populates="totp")


class RecoveryCode(Base):
    __tablename__: str = "recovery_codes"
    __table_args__: tuple[Any, ...] = (
        Index("ix_recovery_codes_user_hash", "user_id", "code_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    user: Mapped["User"] = relationship(back_populates="recovery_codes")


class TempTokenUsage(Base):
    """跟踪用于 2FA 验证的一次性临时令牌。"""

    __tablename__: str = "temp_token_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="2fa")
    txn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class SetupTransaction(Base):
    """绑定到设置临时令牌的一次性 TOTP 设置事务。"""

    __tablename__: str = "setup_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class PendingRegistration(Base):
    """存储待处理的普通注册数据，直到联系方式被验证。"""

    __tablename__: str = "pending_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class RecoveryTransaction(Base):
    """专用的管理员密码恢复事务，支持双重验证。"""

    __tablename__: str = "recovery_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    totp_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="contact_pending")
    failed_contact_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_second_factor_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_setup_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_jti_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class PasskeyCredential(Base):
    __tablename__: str = "passkey_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    user: Mapped["User"] = relationship(back_populates="passkey_credentials")


class AuditLog(Base):
    __tablename__: str = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class PasskeyChallenge(Base):
    """WebAuthn 挑战码，跨 worker 共享，过期自动失效。"""

    __tablename__: str = "passkey_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challenge_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    challenge: Mapped[str] = mapped_column(Text, nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class OAuthState(Base):
    """临时的 OAuth 状态令牌，用于 CSRF 保护。"""

    __tablename__: str = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)  # "login" or "bind"
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )  # 仅 bind 场景：发起绑定的用户
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
