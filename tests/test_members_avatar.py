"""预置成员头像代理端点(/api/v1/avatars/{name}) 的 TDD 测试。

端点在 members 模块，读 storage 后端；本测试用 local 后端 + tmp 目录，验证可读与 404。
"""

import pathlib
from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
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
    from app.modules.storage.factory import get_storage

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    get_storage.cache_clear()  # factory 是 lru_cache 单例，清缓存让新 root_dir 生效

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
        get_storage.cache_clear()


async def _place_avatar(tmp_path: pathlib.Path, name: str, data: bytes) -> None:
    """把预置头像写到 local 后端 key ``avatars/{name}`` 对应磁盘路径。"""
    dest = tmp_path / "avatars" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


class TestPresetAvatarEndpoint:
    @pytest.mark.asyncio
    async def test_serves_avatar_bytes_with_immutable_cache(
        self, client: AsyncClient, tmp_path: pathlib.Path
    ):
        await _place_avatar(tmp_path, "七月花.webp", b"fake-webp-bytes")
        resp = await client.get("/api/v1/avatars/七月花.webp")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.content == b"fake-webp-bytes"

    @pytest.mark.asyncio
    async def test_missing_avatar_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/avatars/no-such.webp")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_squashed_to_basename(
        self, client: AsyncClient, tmp_path: pathlib.Path
    ):
        # 只取 basename：../secret 被折叠为 key avatars/secret，不读目录外文件
        await _place_avatar(tmp_path, "ok.webp", b"ok")
        secret = tmp_path / "secret"
        secret.write_bytes(b"leak")
        resp = await client.get("/api/v1/avatars/..%2Fsecret")
        # basename 是 secret（无扩展名）→ 存储中无 avatars/secret → 404（而非读取 tmp 根的 secret）
        assert resp.status_code == 404
