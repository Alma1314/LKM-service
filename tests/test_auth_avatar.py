"""Phase 2-D：头像上传 + 对象存储代理端点(auth/avatar) 的 TDD 测试。"""

import asyncio
import pathlib
import re
from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import CommonErr
from app.db.models import Profile, User
from app.modules.auth.errors import AuthErr
from app.modules.auth.security import create_access_token, hashpwd

_KEY_RE = re.compile(r"^avatars/\d+/v\d+\.webp$")


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    """内存 aiosqlite 会话，覆盖主 app 的 get_session 依赖。"""
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base
    from app.db.session import get_read_session, get_session
    from app.main import app as fastapi_app

    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: AsyncSession = SessionLocal()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(get_read_session, None)


@pytest.fixture
async def client(
    db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient]:
    from httpx import ASGITransport

    from app.core.config import settings
    from app.db.session import get_read_session, get_session
    from app.main import app as fastapi_app

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        yield db

    fastapi_app.dependency_overrides[get_session] = override_get_session
    fastapi_app.dependency_overrides[get_read_session] = override_get_session
    transport = ASGITransport(app=fastapi_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(get_read_session, None)


async def _user(
    db: AsyncSession,
    username: str = "avatar",
    email: str = "avatar@example.com",
) -> int:
    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname="头像用户"))
    await db.flush()
    return user.id


async def _avatar_key(db: AsyncSession, user_id: int) -> str | None:
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .one()
    )
    return profile.avatar


async def _physical_exists(tmp_path: pathlib.Path, key: str) -> bool:
    return (tmp_path / key).exists()


class TestAvatarUpload:
    async def _authed(self, db: AsyncSession) -> tuple[int, str]:
        user_id = await _user(db)
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    async def test_upload_sets_profile_avatar_key(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id, token = await self._authed(db)

        resp = await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("a.webp", b"\x00\x01\x02", "image/webp")},
        )

        assert resp.status_code == 200
        key = await _avatar_key(db, user_id)
        assert key is not None
        assert _KEY_RE.match(key)
        assert resp.json()["data"]["avatar"] == key

    async def test_reupload_uses_new_key_and_removes_old(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tmp_path: pathlib.Path,
    ):
        user_id, token = await self._authed(db)
        files = {"file": ("a.webp", b"\x00\x01\x02", "image/webp")}
        await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
        )
        old_key = await _avatar_key(db, user_id)
        assert old_key is not None
        assert await _physical_exists(tmp_path, old_key)

        resp = await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
        )

        assert resp.status_code == 200
        new_key = await _avatar_key(db, user_id)
        assert new_key is not None
        assert new_key != old_key
        # 旧 key 文件已删除，新 key 文件存在
        assert not await _physical_exists(tmp_path, old_key)
        assert await _physical_exists(tmp_path, new_key)

    async def test_reject_oversized_upload(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import app.modules.auth.service as svc

        user_id, token = await self._authed(db)
        await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("a.webp", b"\x00\x00", "image/webp")},
        )
        # 缩小上限以在测试中触发 413（等价于 >2MB 超限）
        monkeypatch.setattr(svc, "AVATAR_MAX_BYTES", 4)

        resp = await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("b.webp", b"\x00" * 100, "image/webp")},
        )

        assert resp.status_code == 413
        assert resp.json()["code"] == AuthErr.TOO_LARGE
        # profile.avatar 未变；超限未落盘（目录只剩旧 key 那一份）
        key = await _avatar_key(db, user_id)
        assert key is not None
        # 超限上传未产生新文件（本 key 对应的 .webp 仍只有一份）
        files = await asyncio.to_thread(lambda: list(tmp_path.rglob("*.webp")))
        assert len(files) == 1

    async def test_upload_requires_auth(
        self, client: AsyncClient, db: AsyncSession
    ):
        resp = await client.post(
            "/api/v1/auth/avatar",
            files={"file": ("a.webp", b"\x00", "image/webp")},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN


class TestAvatarServe:
    async def _authed(self, db: AsyncSession) -> tuple[int, str]:
        user_id = await _user(db)
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    async def test_serve_returns_bytes_immutable(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tmp_path: pathlib.Path,
    ):
        payload = b"\xff\xd8\xff\xe0 fake webp"
        user_id, token = await self._authed(db)
        await client.post(
            "/api/v1/auth/avatar",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("a.webp", payload, "image/webp")},
        )

        resp = await client.get(f"/api/v1/auth/avatar/{user_id}")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/webp")
        assert "immutable" in resp.headers["cache-control"]
        assert resp.content == payload

    async def test_serve_404_without_avatar(
        self, client: AsyncClient, db: AsyncSession
    ):
        resp = await client.get("/api/v1/auth/avatar/1")

        assert resp.status_code == 404
        assert resp.json()["code"] == AuthErr.AVATAR_NOT_FOUND

    async def test_serve_404_for_unknown_user(
        self, client: AsyncClient, db: AsyncSession
    ):
        resp = await client.get("/api/v1/auth/avatar/999")

        assert resp.status_code == 404
        assert resp.json()["code"] == AuthErr.AVATAR_NOT_FOUND
