"""Tests for email/phone binding endpoints (router_settings.py).

Covers:
- Bind email request + verify with upgrade local->normal
- Bind phone request + verify
- Error cases: duplicate email/phone, wrong code
"""

import json
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr
from app.modules.auth.errors import AuthErr
from app.modules.auth.deps import CurrentUser
from app.modules.auth.router_settings import BindEmailVerify, BindPhoneVerify
from app.modules.auth.schemas import UnbindRequest
from app.db.models import User
import app.modules.auth.models  # pyright: ignore[reportUnusedImport] — ensure auth tables (refresh_tokens, etc.) are created


def _FakeCurrentUser(id: int, account_level: str = "local", role: str = "member") -> CurrentUser:
    """测试辅助：构造一个满足 ``CurrentUser`` 类型的用户上下文。"""
    return CurrentUser(id=id, account_level=account_level, role=role)


def _unwrap(response: Any) -> dict[str, Any]:
    """Extract the data dict from a JSONResponse returned by @respond."""
    return json.loads(response.body.decode())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# service helpers (mimic test_auth_service pattern)
# ---------------------------------------------------------------------------


async def _reg_local(db: AsyncSession, username: str = "alice", password: str = "secret123456") -> dict[str, Any]:
    from app.modules.auth.schemas import UserRegLocal

    svc = _service()
    return await svc.register_local(db, UserRegLocal(username=username, password=password))


async def _get_user(db: AsyncSession, user_id: int) -> User:
    from app.db.models import User

    # 测试均为“先建后查”，必然命中，返回类型直接按 User 处理
    return cast(User, (await db.execute(select(User).where(User.id == user_id))).scalars().first())


def _service():
    from app.modules.auth import service_auth

    return service_auth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBindEmail:
    """Bind email request + verify, covering auto-upgrade local->normal."""

    async def should_bind_email_and_upgrade_local_to_normal(self, db: AsyncSession):
        """Full happy path: request code, verify, email bound, account upgraded."""
        # Arrange: create a local user
        reg_result = await _reg_local(db, username="alice")
        user_id = reg_result["user_id"]
        assert (await _get_user(db, user_id)).account_level == "local"

        # Act: request email binding（验证码直接取自 create_email_verification 返回值）
        from app.modules.auth.service_verify import create_email_verification

        code, _ = await create_email_verification(db, "alice@example.com", "bind")

        # Now use the router function directly
        from app.modules.auth.router_settings import bind_email_verify

        result = await bind_email_verify(
            body=BindEmailVerify(email="alice@example.com", code=code),
            cur=_FakeCurrentUser(user_id),
            db=db,
        )

        # Assert
        data = _unwrap(result)
        assert data["data"]["message"] == "Email bound successfully"

        user = await _get_user(db, user_id)
        assert user.email == "alice@example.com"
        # account should be upgraded from local to normal
        assert user.account_level == "normal"

    async def should_reject_duplicate_email(self, db: AsyncSession):
        """Should fail if email is already taken by another user."""
        # Create two local users
        reg1 = await _reg_local(db, username="alice")
        reg2 = await _reg_local(db, username="bob")

        from app.modules.auth.service_verify import create_email_verification

        # Bind email to alice directly
        user1 = await _get_user(db, reg1["user_id"])
        user1.email = "same@example.com"
        await db.flush()

        # Try to bind the same email to bob
        code, _ = await create_email_verification(db, "same@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        with pytest.raises(BizError) as exc:
            await bind_email_verify(
                body=BindEmailVerify(email="same@example.com", code=code),
                cur=_FakeCurrentUser(reg2["user_id"]),
                db=db,
            )
        assert exc.value.errcode == AuthErr.ALREADY_REGISTERED

    async def should_reject_wrong_code(self, db: AsyncSession):
        """Should fail with wrong verification code."""
        reg = await _reg_local(db, username="alice")

        from app.modules.auth.service_verify import create_email_verification

        await create_email_verification(db, "alice@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        with pytest.raises(BizError) as exc:
            await bind_email_verify(
                body=BindEmailVerify(email="alice@example.com", code="000000"),
                cur=_FakeCurrentUser(reg["user_id"]),
                db=db,
            )
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID


class TestBindPhone:
    """Bind phone request + verify."""

    async def should_bind_phone_and_upgrade_local_to_normal(self, db: AsyncSession):
        """Full happy path: request code, verify, phone bound, account upgraded."""
        reg = await _reg_local(db, username="alice")
        user_id = reg["user_id"]
        assert (await _get_user(db, user_id)).account_level == "local"

        from app.modules.auth.service_verify import create_phone_verification

        code, _ = await create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        result = await bind_phone_verify(
            body=BindPhoneVerify(phone="13800001111", code=code),
            cur=_FakeCurrentUser(user_id),
            db=db,
        )

        data = _unwrap(result)
        assert data["data"]["message"] == "Phone bound successfully"

        user = await _get_user(db, user_id)
        assert user.phone == "13800001111"
        assert user.account_level == "normal"

    async def should_reject_duplicate_phone(self, db: AsyncSession):
        """Should fail if phone already taken."""
        reg1 = await _reg_local(db, username="alice")
        reg2 = await _reg_local(db, username="bob")

        # Bind phone to alice directly
        user1 = await _get_user(db, reg1["user_id"])
        user1.phone = "13800001111"
        await db.flush()

        from app.modules.auth.service_verify import create_phone_verification

        code, _ = await create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        with pytest.raises(BizError) as exc:
            await bind_phone_verify(
                body=BindPhoneVerify(phone="13800001111", code=code),
                cur=_FakeCurrentUser(reg2["user_id"]),
                db=db,
            )
        assert exc.value.errcode == AuthErr.ALREADY_REGISTERED

    async def should_reject_wrong_code(self, db: AsyncSession):
        """Should fail with wrong verification code."""
        reg = await _reg_local(db, username="alice")

        from app.modules.auth.service_verify import create_phone_verification

        await create_phone_verification(db, "13800001111", "bind")

        from app.modules.auth.router_settings import bind_phone_verify

        with pytest.raises(BizError) as exc:
            await bind_phone_verify(
                body=BindPhoneVerify(phone="13800001111", code="000000"),
                cur=_FakeCurrentUser(reg["user_id"]),
                db=db,
            )
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID


class TestBindEmailUpgrade:
    """Specifically test that bind email upgrades local->normal."""

    async def should_upgrade_when_binding_email(self, db: AsyncSession):
        """Bind email to a local user: account_level must become normal."""
        reg = await _reg_local(db, username="upgrademe")
        user_id = reg["user_id"]
        user = await _get_user(db, user_id)
        assert user.account_level == "local"
        assert user.email is None

        from app.modules.auth.service_verify import create_email_verification

        code, _ = await create_email_verification(db, "upgrade@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        await bind_email_verify(
            body=BindEmailVerify(email="upgrade@example.com", code=code),
            cur=_FakeCurrentUser(user_id),
            db=db,
        )

        user = await _get_user(db, user_id)
        assert user.email == "upgrade@example.com"
        assert user.account_level == "normal"

    async def should_not_downgrade_normal_user(self, db: AsyncSession):
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
        await db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        await db.flush()
        user_id = user.id

        # Bind a different email (the user already has one, but we're binding another)
        from app.modules.auth.service_verify import create_email_verification

        code, _ = await create_email_verification(db, "another@example.com", "bind")

        from app.modules.auth.router_settings import bind_email_verify

        await bind_email_verify(
            body=BindEmailVerify(email="another@example.com", code=code),
            cur=_FakeCurrentUser(user_id, account_level="normal"),
            db=db,
        )

        user = await _get_user(db, user_id)
        # Already normal, should not have been changed
        assert user.account_level == "normal"


class TestGetSettings:
    """GET /auth/settings — 查询绑定状态。"""

    def _unwrap(self, response: Any) -> dict[str, Any]:
        return json.loads(response.body.decode())

    async def should_return_binding_state(self, db: AsyncSession):
        from app.db.models import User, Profile

        user = User(username="bindstate", email="a@b.com", phone="13800001111",
                    hashed_password="x", account_level="normal")
        db.add(user)
        await db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        await db.flush()

        from app.modules.auth.models import TOTP
        db.add(TOTP(user_id=user.id, secret="s", enabled=True))
        await db.flush()

        from app.modules.auth.router_settings import get_settings

        data = self._unwrap(await get_settings(cur=_FakeCurrentUser(user.id, account_level="normal"), db=db))
        assert data["data"]["email"] == "a@b.com"
        assert data["data"]["phone"] == "13800001111"
        assert data["data"]["github"] is None
        assert data["data"]["has_2fa"] is True


class TestUnbind:
    """DELETE /auth/settings/{type} — 解绑 + 2FA 门槛 + 保留一种登录方式。"""

    async def _reg_with_bindings(self, db: AsyncSession, email: str = "a@b.com", phone: str = "13800001111") -> User:
        from app.db.models import User, Profile
        user = User(username="unbind", email=email, phone=phone,
                    hashed_password="x", account_level="normal")
        db.add(user)
        await db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        await db.flush()
        return user

    async def should_unbind_email_without_2fa(self, db: AsyncSession):
        from app.db.models import User
        user = await self._reg_with_bindings(db)
        from app.modules.auth.router_settings import unbind

        data = _unwrap(await unbind("email", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db))
        assert data["data"]["message"] == "email unbound"
        # 直接用标量列查询，避免命中身份映射中已过期的 User 对象触发惰性加载
        assert await db.scalar(select(User.email).where(User.id == user.id)) is None

    async def should_reject_unbind_when_only_one_way_left(self, db: AsyncSession):
        # 只有 phone，没有 email/github → 解绑 email 会触发“保留一种”守卫（虽然 email 本来就空，走 phone 侧测试更贴）
        from app.db.models import User, Profile
        user = User(username="onlyphone", phone="13800009999",
                    hashed_password="x", account_level="normal")
        db.add(user)
        await db.flush()
        db.add(Profile(user_id=user.id, role="member"))
        await db.flush()
        # 绑定另一个联系方式以便 email 存在可解绑，但仅剩 phone 时会拒绝
        user.email = "a@b.com"
        await db.flush()

        from app.modules.auth.router_settings import unbind
        from app.core.err import BizError

        # 先解绑 phone，使仅剩 email
        _unwrap(await unbind("phone", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db))
        # 再解绑 email，将无任何登录方式 → 应拒绝
        with pytest.raises(BizError) as exc:
            await unbind("email", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db)
        assert exc.value.errcode == CommonErr.INVALID_INPUT

    async def should_require_totp_when_2fa_enabled(self, db: AsyncSession):
        user = await self._reg_with_bindings(db)
        from app.modules.auth.models import TOTP
        db.add(TOTP(user_id=user.id, secret="s", enabled=True))
        await db.flush()

        from app.core.err import BizError
        from app.modules.auth.router_settings import unbind

        with pytest.raises(BizError) as exc:
            await unbind("email", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db)
        assert exc.value.errcode == AuthErr.TOTP_CODE_INVALID

    async def should_unbind_github(self, db: AsyncSession):
        user = await self._reg_with_bindings(db)
        from app.modules.auth.models import UserOAuth
        db.add(UserOAuth(user_id=user.id, provider="github",
                         provider_user_id="123", provider_email="gh@example.com"))
        await db.flush()
        from app.modules.auth.router_settings import unbind

        data = _unwrap(await unbind("github", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db))
        assert data["data"]["message"] == "github unbound"
        # 用标量列查询判定行已删除，绕过过期身份映射对象
        assert (await db.execute(select(UserOAuth.id).where(UserOAuth.user_id == user.id))).scalars().first() is None

    async def should_reject_invalid_type(self, db: AsyncSession):
        user = await self._reg_with_bindings(db)
        from app.core.err import BizError
        from app.modules.auth.router_settings import unbind

        with pytest.raises(BizError) as exc:
            await unbind("wechat", UnbindRequest(code=None), cur=_FakeCurrentUser(user.id, account_level="normal"), db=db)
        assert exc.value.errcode == CommonErr.INVALID_INPUT
