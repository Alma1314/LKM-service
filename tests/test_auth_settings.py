"""Tests for email/phone binding endpoints (router_settings.py).

Covers:
- Bind email request + verify with upgrade local->normal
- Bind phone request + verify
- Error cases: duplicate email/phone, wrong code
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.err import BizError, ErrCode
from app.db.models import Base
import app.modules.auth.models  # pyright: ignore[reportUnusedImport]


def _unwrap(response):
    """Extract the data dict from a JSONResponse returned by @respond."""
    return json.loads(response.body.decode())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# service helpers (mimic test_auth_service pattern)
# ---------------------------------------------------------------------------


def _reg_local(db, username="alice", password="secret123456"):
    from app.modules.auth.schemas import UserRegLocal

    svc = _service()
    return svc.register_local(db, UserRegLocal(username=username, password=password))


def _get_user(db, user_id: int):
    from app.db.models import User

    return db.query(User).filter(User.id == user_id).first()


def _service():
    from app.modules.auth import service_auth

    return service_auth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBindEmail:
    """Bind email request + verify, covering auto-upgrade local->normal."""

    def should_bind_email_and_upgrade_local_to_normal(self, db):
        """Full happy path: request code, verify, email bound, account upgraded."""
        # Arrange: create a local user
        from app.db.models import User

        reg_result = _reg_local(db, username="alice")
        user_id = reg_result["user_id"]
        assert _get_user(db, user_id).account_level == "local"

        # Stub providers so we can capture the code
        captured = {}

        async def fake_send_code(email, code):
            captured["code"] = code

        # Act: request email binding
        from app.modules.auth.service_verify import create_email_verification

        code, record_id = create_email_verification(db, "alice@example.com", "bind")
        captured["code"] = code

        # Now use the router function directly
        from app.modules.auth.router_settings import bind_email_verify

        class FakeCurrentUser:
            id = user_id
            account_level = "local"
            role = "member"

        result = bind_email_verify(
            body=type("Body", (), {"email": "alice@example.com", "code": code})(),
            cur=FakeCurrentUser(),
            db=db,
        )

        # Assert
        data = _unwrap(result)
        assert data["data"]["message"] == "Email bound successfully"

        user = _get_user(db, user_id)
        assert user.email == "alice@example.com"
        # account should be upgraded from local to normal
        assert user.account_level == "normal"

    def should_reject_duplicate_email(self, db):
        """Should fail if email is already taken by another user."""
        # Create two local users
        reg1 = _reg_local(db, username="alice")
        reg2 = _reg_local(db, username="bob")

        from app.modules.auth.service_verify import create_email_verification, consume_email_code

        # Bind email to alice directly
        user1 = _get_user(db, reg1["user_id"])
        user1.email = "same@example.com"
        db.flush()

        # Try to bind the same email to bob
        code, record_id = create_email_verification(db, "same@example.com", "bind")

        class FakeCurrentUser:
            id = reg2["user_id"]
            account_level = "local"
            role = "member"

        from app.modules.auth.router_settings import bind_email_verify

        with pytest.raises(BizError) as exc:
            bind_email_verify(
                body=type("Body", (), {"email": "same@example.com", "code": code})(),
                cur=FakeCurrentUser(),
                db=db,
            )
        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED

    def should_reject_wrong_code(self, db):
        """Should fail with wrong verification code."""
        reg = _reg_local(db, username="alice")

        from app.modules.auth.service_verify import create_email_verification

        create_email_verification(db, "alice@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        class FakeCurrentUser:
            id = reg["user_id"]
            account_level = "local"
            role = "member"

        with pytest.raises(BizError) as exc:
            bind_email_verify(
                body=type("Body", (), {"email": "alice@example.com", "code": "000000"})(),
                cur=FakeCurrentUser(),
                db=db,
            )
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID


class TestBindPhone:
    """Bind phone request + verify."""

    def should_bind_phone_and_upgrade_local_to_normal(self, db):
        """Full happy path: request code, verify, phone bound, account upgraded."""
        reg = _reg_local(db, username="alice")
        user_id = reg["user_id"]
        assert _get_user(db, user_id).account_level == "local"

        from app.modules.auth.service_verify import create_phone_verification

        code, record_id = create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        class FakeCurrentUser:
            id = user_id
            account_level = "local"
            role = "member"

        result = bind_phone_verify(
            body=type("Body", (), {"phone": "13800001111", "code": code})(),
            cur=FakeCurrentUser(),
            db=db,
        )

        data = _unwrap(result)
        assert data["data"]["message"] == "Phone bound successfully"

        user = _get_user(db, user_id)
        assert user.phone == "13800001111"
        assert user.account_level == "normal"

    def should_reject_duplicate_phone(self, db):
        """Should fail if phone already taken."""
        reg1 = _reg_local(db, username="alice")
        reg2 = _reg_local(db, username="bob")

        # Bind phone to alice directly
        user1 = _get_user(db, reg1["user_id"])
        user1.phone = "13800001111"
        db.flush()

        from app.modules.auth.service_verify import create_phone_verification

        code, record_id = create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        class FakeCurrentUser:
            id = reg2["user_id"]
            account_level = "local"
            role = "member"

        with pytest.raises(BizError) as exc:
            bind_phone_verify(
                body=type("Body", (), {"phone": "13800001111", "code": code})(),
                cur=FakeCurrentUser(),
                db=db,
            )
        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED

    def should_reject_wrong_code(self, db):
        """Should fail with wrong verification code."""
        reg = _reg_local(db, username="alice")

        from app.modules.auth.service_verify import create_phone_verification

        create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        class FakeCurrentUser:
            id = reg["user_id"]
            account_level = "local"
            role = "member"

        with pytest.raises(BizError) as exc:
            bind_phone_verify(
                body=type("Body", (), {"phone": "13800001111", "code": "000000"})(),
                cur=FakeCurrentUser(),
                db=db,
            )
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID


class TestBindEmailUpgrade:
    """Specifically test that bind email upgrades local->normal."""

    def should_upgrade_when_binding_email(self, db):
        """Bind email to a local user: account_level must become normal."""
        reg = _reg_local(db, username="upgrademe")
        user_id = reg["user_id"]
        user = _get_user(db, user_id)
        assert user.account_level == "local"
        assert user.email is None

        from app.modules.auth.service_verify import create_email_verification

        code, _ = create_email_verification(db, "upgrade@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        class FakeCurrentUser:
            id = user_id
            account_level = "local"
            role = "member"

        bind_email_verify(
            body=type("Body", (), {"email": "upgrade@example.com", "code": code})(),
            cur=FakeCurrentUser(),
            db=db,
        )

        user = _get_user(db, user_id)
        assert user.email == "upgrade@example.com"
        assert user.account_level == "normal"

    def should_not_downgrade_normal_user(self, db):
        """Binding email to an already-normal user: should stay normal."""
        from app.db.models import User, Profile

        # Create an already-normal user
        user = User(
            username="normaluser",
            email="normal@example.com",
            hashed_password="x",
            account_level="normal",
        )
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        db.flush()
        user_id = user.id

        # Bind a different email (the user already has one, but we're binding another)
        from app.modules.auth.service_verify import create_email_verification

        code, _ = create_email_verification(db, "another@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        class FakeCurrentUser:
            id = user_id
            account_level = "normal"
            role = "member"

        bind_email_verify(
            body=type("Body", (), {"email": "another@example.com", "code": code})(),
            cur=FakeCurrentUser(),
            db=db,
        )

        user = _get_user(db, user_id)
        # Already normal, should not have been changed
        assert user.account_level == "normal"


class TestGetSettings:
    """GET /auth/settings — 查询绑定状态。"""

    def _unwrap(self, response):
        return json.loads(response.body.decode())

    def should_return_binding_state(self, db):
        from app.db.models import User, Profile

        user = User(username="bindstate", email="a@b.com", phone="13800001111",
                    hashed_password="x", account_level="normal")
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        db.flush()

        from app.modules.auth.models import TOTP
        db.add(TOTP(user_id=user.id, secret="s", enabled=True))
        db.flush()

        from app.modules.auth.router_settings import get_settings

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        data = self._unwrap(get_settings(cur=FakeCurrentUser(), db=db))
        assert data["data"]["email"] == "a@b.com"
        assert data["data"]["phone"] == "13800001111"
        assert data["data"]["github"] is None
        assert data["data"]["has_2fa"] is True


class TestUnbind:
    """DELETE /auth/settings/{type} — 解绑 + 2FA 门槛 + 保留一种登录方式。"""

    def _reg_with_bindings(self, db, email="a@b.com", phone="13800001111"):
        from app.db.models import User, Profile
        user = User(username="unbind", email=email, phone=phone,
                    hashed_password="x", account_level="normal")
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        db.flush()
        return user

    def should_unbind_email_without_2fa(self, db):
        from app.db.models import User
        user = self._reg_with_bindings(db)
        from app.modules.auth.router_settings import unbind

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        data = json.loads(unbind("email", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db).body.decode())
        assert data["data"]["message"] == "email unbound"
        db.expire_all()
        assert db.query(User).filter(User.id == user.id).first().email is None

    def should_reject_unbind_when_only_one_way_left(self, db):
        # 只有 phone，没有 email/github → 解绑 email 会触发“保留一种”守卫（虽然 email 本来就空，走 phone 侧测试更贴）
        from app.db.models import User, Profile
        user = User(username="onlyphone", phone="13800009999",
                    hashed_password="x", account_level="normal")
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        db.flush()
        # 绑定另一个联系方式以便 email 存在可解绑，但仅剩 phone 时会拒绝
        user.email = "a@b.com"
        db.flush()

        from app.modules.auth.router_settings import unbind
        from app.core.err import BizError, ErrCode

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        # 先解绑 phone，使仅剩 email
        json.loads(unbind("phone", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db).body.decode())
        # 再解绑 email，将无任何登录方式 → 应拒绝
        with pytest.raises(BizError) as exc:
            unbind("email", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db)
        assert exc.value.errcode == ErrCode.INVALID_INPUT

    def should_require_totp_when_2fa_enabled(self, db):
        user = self._reg_with_bindings(db)
        from app.modules.auth.models import TOTP
        db.add(TOTP(user_id=user.id, secret="s", enabled=True))
        db.flush()

        from app.core.err import BizError, ErrCode
        from app.modules.auth.router_settings import unbind

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        with pytest.raises(BizError) as exc:
            unbind("email", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db)
        assert exc.value.errcode == ErrCode.TOTP_CODE_INVALID

    def should_unbind_github(self, db):
        user = self._reg_with_bindings(db)
        from app.modules.auth.models import UserOAuth
        db.add(UserOAuth(user_id=user.id, provider="github",
                         provider_user_id="123", provider_email="gh@example.com"))
        db.flush()
        from app.modules.auth.router_settings import unbind

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        data = json.loads(unbind("github", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db).body.decode())
        assert data["data"]["message"] == "github unbound"
        db.expire_all()
        assert db.query(UserOAuth).filter(UserOAuth.user_id == user.id).first() is None

    def should_reject_invalid_type(self, db):
        user = self._reg_with_bindings(db)
        from app.core.err import BizError, ErrCode
        from app.modules.auth.router_settings import unbind

        class FakeCurrentUser:
            id = user.id
            account_level = "normal"
            role = "member"

        with pytest.raises(BizError) as exc:
            unbind("wechat", type("Body", (), {"code": None})(), cur=FakeCurrentUser(), db=db)
        assert exc.value.errcode == ErrCode.INVALID_INPUT
