"""Tests for Magic Link login (Task 13)."""

import asyncio
import datetime as dt
import hashlib
import secrets

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.err import BizError
from app.modules.auth.errors import AuthErr
from app.db.models import Base, User
import app.modules.auth.models  # noqa: F401
from app.modules.auth.models import MagicLink, TOTP
from app.modules.auth.providers.console import ConsoleEmailProvider


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal: sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _service():
    from app.modules.auth import service_auth
    return service_auth


def _create_user(db, username="alice", email="alice@example.com",
                 password="secret123456", account_level="normal"):
    """Create a user with the given parameters and return it."""
    from app.modules.auth.security import hashpwd
    from app.db.models import Profile

    user = User(
        username=username,
        email=email,
        hashed_password=hashpwd(password),
        account_level=account_level,
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, role="member"))
    db.flush()
    return user


def _make_magic_link(db, email, purpose="login", used=False, expired=False):
    """Create a MagicLink record and return (raw_token, record)."""
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    if expired:
        expires = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    else:
        expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)).isoformat()

    record = MagicLink(
        email=email,
        token_hash=token_hash,
        purpose=purpose,
        expires_at=expires,
        used=used,
    )
    db.add(record)
    db.flush()
    return raw_token, record


class TestRequestMagicLink:
    def should_persist_magic_link_record(self, db):
        _create_user(db, username="testuser", email="test@example.com")
        svc = _service()

        async def _call():
            svc.request_magic_link(
                db, "test@example.com", ConsoleEmailProvider(),
                purpose="login",
            )

        asyncio.run(_call())

        records = db.query(MagicLink).filter(MagicLink.email == "test@example.com").all()
        assert len(records) == 1
        record = records[0]
        assert record.purpose == "login"
        assert record.used is False
        assert len(record.token_hash) == 64  # SHA-256 hex

    def should_store_different_tokens_for_repeated_requests(self, db):
        _create_user(db, username="user_a", email="a@b.com")
        svc = _service()

        async def _call():
            svc.request_magic_link(db, "a@b.com", ConsoleEmailProvider(), purpose="login")
            svc.request_magic_link(db, "a@b.com", ConsoleEmailProvider(), purpose="login")

        asyncio.run(_call())

        records = db.query(MagicLink).filter(MagicLink.email == "a@b.com").all()
        assert len(records) == 2
        assert records[0].token_hash != records[1].token_hash


class TestVerifyMagicLink:
    def should_return_auth_tokens_on_valid_link(self, db):
        _create_user(db, email="alice@example.com")
        raw_token, _ = _make_magic_link(db, "alice@example.com")

        svc = _service()
        result = svc.verify_magic_link(db, raw_token, purpose="login")

        assert result["access_token"] is not None
        assert result["refresh_token"] is not None
        assert result["user_id"] == 1
        assert result["account_level"] == "normal"
        assert result["requires_2fa"] is False

    def should_mark_link_as_used_after_success(self, db):
        _create_user(db, email="alice@example.com")
        raw_token, record = _make_magic_link(db, "alice@example.com")

        svc = _service()
        svc.verify_magic_link(db, raw_token, purpose="login")

        db.expire_all()
        updated = db.query(MagicLink).filter(MagicLink.id == record.id).first()
        assert updated.used is True

    def should_reject_expired_magic_link(self, db):
        _create_user(db, email="alice@example.com")
        raw_token, _ = _make_magic_link(db, "alice@example.com", expired=True)

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="login")
        assert exc.value.errcode == AuthErr.TOKEN_EXPIRED

    def should_reject_already_used_magic_link(self, db):
        _create_user(db, email="alice@example.com")
        raw_token, _ = _make_magic_link(db, "alice@example.com", used=True)

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="login")
        assert exc.value.errcode == AuthErr.TOKEN_INVALID

    def should_reject_local_user(self, db):
        _create_user(db, email="bob@local.com", account_level="local")
        raw_token, _ = _make_magic_link(db, "bob@local.com")

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="login")
        assert exc.value.errcode == AuthErr.ACCOUNT_LEVEL_INSUFFICIENT

    def should_reject_purpose_mismatch(self, db):
        _create_user(db, email="alice@example.com")
        raw_token, _ = _make_magic_link(db, "alice@example.com", purpose="login")

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="reset")
        assert exc.value.errcode == AuthErr.TOKEN_INVALID

    def should_reject_unknown_token(self, db):
        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, "nonexistent-token", purpose="login")
        assert exc.value.errcode == AuthErr.TOKEN_INVALID

    def should_reject_missing_user(self, db):
        # No user created for this email
        raw_token, _ = _make_magic_link(db, "no-user@example.com")

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="login")
        assert exc.value.errcode == AuthErr.USER_NOT_FOUND

    def should_reject_admin_without_totp(self, db):
        _create_user(db, email="admin@example.com", account_level="admin")
        raw_token, _ = _make_magic_link(db, "admin@example.com")

        svc = _service()
        with pytest.raises(BizError) as exc:
            svc.verify_magic_link(db, raw_token, purpose="login")
        assert exc.value.errcode == AuthErr.TOTP_SETUP_REQUIRED

    def should_return_temp_token_when_2fa_required(self, db):
        user = _create_user(db, email="secure@example.com", account_level="normal")
        # enable TOTP
        totp = TOTP(user_id=user.id, secret="MZXW6YTBOJQXI33F", enabled=True)
        db.add(totp)
        db.flush()

        raw_token, _ = _make_magic_link(db, "secure@example.com")

        svc = _service()
        result = svc.verify_magic_link(db, raw_token, purpose="login")
        assert result["requires_2fa"] is True
        assert result["temp_token"] is not None
        assert result["access_token"] is None
        assert result["refresh_token"] is None
