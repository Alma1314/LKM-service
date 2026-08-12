import asyncio
import io
import pathlib
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.modules.auth.models  # pyright: ignore[reportUnusedImport] ensure auth tables registered
from app.core.err import BizError, CommonErr
from app.db.models import Base, LibraryFile, Profile, User
from app.db.session import get_session
from app.main import app
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.files.errors import FileErr
from app.modules.files.schemas import FileCreate, FileInfo
from app.modules.files.service import (
    bump_download,
    create_file,
    get_file,
    list_files,
)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
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


@pytest.fixture
async def client(
    db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient]:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _user(
    db: AsyncSession,
    username: str = "alice",
    email: str = "alice@example.com",
    nickname: str | None = None,
) -> int:
    user = User(
        username=username,
        email=email,
        hashed_password=hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname=nickname))
    await db.flush()
    return user.id


async def _file(
    db: AsyncSession,
    uploader_id: int = 1,
    original_name: str = "讲义.pdf",
    category_id: str = "math",
    tags: tuple[str, ...] = ("数学",),
) -> FileInfo:
    return await create_file(
        db,
        uploader_id,
        FileCreate(
            original_name=original_name,
            mime_type="application/pdf",
            category_id=category_id,
            description="一份讲义",
            tags=list(tags),
        ),
        stream=io.BytesIO(b"%PDF-1.4 fake content"),
    )


class TestFilesService:
    async def should_create_file_with_nickname(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db, nickname="爱丽丝")

        f = await _file(db, uploader_id=user_id)

        assert f.id == 1
        assert f.uploader_id == user_id
        assert f.uploader_name == "爱丽丝"
        assert f.tags == ["数学"]
        assert f.status == "pending"
        assert f.download_count == 0
        assert f.view_count == 0
        stored = (
            (await db.execute(select(LibraryFile).where(LibraryFile.id == f.id)))
            .scalars()
            .one()
        )
        assert (tmp_path / stored.stored_name).read_bytes() == b"%PDF-1.4 fake content"

    async def should_use_username_when_no_nickname(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db, username="bob", email="bob@example.com")

        f = await _file(db, uploader_id=user_id)

        assert f.uploader_name == "bob"

    async def should_list_files_paginated(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)
        await _file(db, uploader_id=user_id, original_name="文件一.pdf")
        await _file(db, uploader_id=user_id, original_name="文件二.pdf")

        page = await list_files(db, page=1, limit=1)

        assert page.total == 2
        assert page.pages == 2
        assert len(page.items) == 1
        assert page.items[0].original_name == "文件二.pdf"

    async def should_filter_files_by_category(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)
        await _file(db, uploader_id=user_id, category_id="math")
        await _file(
            db, uploader_id=user_id, original_name="物理题.pdf", category_id="physics"
        )

        page = await list_files(db, category_id="math")

        assert page.total == 1
        assert page.items[0].category_id == "math"

    async def should_sort_by_downloads(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)
        hot = await _file(db, uploader_id=user_id, original_name="热门.zip")
        _ = await _file(db, uploader_id=user_id, original_name="冷门.pdf")
        await bump_download(db, hot.id)
        await bump_download(db, hot.id)

        page = await list_files(db, sort="downloads")

        assert [f.original_name for f in page.items] == ["热门.zip", "冷门.pdf"]

    async def should_get_file_and_bump_view(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)
        f = await _file(db, uploader_id=user_id)

        first = await get_file(db, f.id, bump_view=True)
        second = await get_file(db, f.id, bump_view=True)

        assert first.view_count == 1
        assert second.view_count == 2

    async def should_reject_nonexistent_file(self, db: AsyncSession):
        with pytest.raises(BizError) as exc:
            await get_file(db, 999)

        assert exc.value.errcode == FileErr.NOT_FOUND

    async def should_increment_download(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)
        f = await _file(db, uploader_id=user_id)

        assert await bump_download(db, f.id) == 1
        assert await bump_download(db, f.id) == 2

    async def should_reject_upload_over_limit(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)

        with pytest.raises(BizError) as exc:
            await create_file(
                db,
                user_id,
                FileCreate(original_name="超大.zip", mime_type="application/zip"),
                stream=io.BytesIO(b"x" * 10),
                max_bytes=5,
            )

        assert exc.value.errcode == FileErr.TOO_LARGE
        assert len((await db.execute(select(LibraryFile))).scalars().all()) == 0
        assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == []

    async def should_accept_upload_at_exact_limit(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = await _user(db)

        f = await create_file(
            db,
            user_id,
            FileCreate(original_name="正好.zip", mime_type="application/zip"),
            stream=io.BytesIO(b"x" * 5),
            max_bytes=5,
        )

        assert f.size == 5


class TestFilesRoutes:
    async def _setup_user(
        self,
        db: AsyncSession,
        username: str = "tester",
        email: str = "tester@example.com",
    ) -> tuple[int, str]:
        user_id = await _user(db, username=username, email=email)
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    async def _upload(
        self,
        client: AsyncClient,
        token: str,
        original_name: str = "讲义.pdf",
        category_id: str = "math",
    ):
        return await client.post(
            "/api/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "file": (
                    original_name,
                    io.BytesIO(b"%PDF-1.4 content"),
                    "application/pdf",
                )
            },
            data={
                "category_id": category_id,
                "description": "测试上传",
                "tags": '["数学"]',
            },
        )

    async def should_reject_upload_without_auth(
        self, client: AsyncClient, db: AsyncSession
    ):
        await self._setup_user(db)
        resp = await client.post(
            "/api/v1/files",
            files={"file": ("a.pdf", io.BytesIO(b"content"), "application/pdf")},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN

    async def should_upload_file_with_token(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id, token = await self._setup_user(db)
        resp = await self._upload(client, token)

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        data = resp.json()["data"]
        assert data["uploader_id"] == user_id
        assert data["original_name"] == "讲义.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size"] == len(b"%PDF-1.4 content")
        assert data["status"] == "pending"
        assert data["tags"] == ["数学"]

    async def should_list_files_publicly(self, client: AsyncClient, db: AsyncSession):
        _, token = await self._setup_user(db)
        await self._upload(client, token, original_name="公开资料.zip")

        resp = await client.get("/api/v1/files")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["original_name"] == "公开资料.zip"

    async def should_get_file_detail(self, client: AsyncClient, db: AsyncSession):
        _, token = await self._setup_user(db)
        created = (await self._upload(client, token)).json()["data"]
        file_id = created["id"]

        resp = await client.get(f"/api/v1/files/{file_id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["view_count"] == 1

    async def should_increment_download_through_api(
        self, client: AsyncClient, db: AsyncSession
    ):
        _, token = await self._setup_user(db)
        created = (await self._upload(client, token)).json()["data"]
        file_id = created["id"]

        resp = await client.post(
            f"/api/v1/files/{file_id}/download",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["download_count"] == 1

    async def should_reject_nonexistent_file_detail(
        self, client: AsyncClient, db: AsyncSession
    ):
        resp = await client.get("/api/v1/files/999")

        assert resp.status_code == 404
        assert resp.json()["code"] == FileErr.NOT_FOUND

    async def should_reject_oversized_upload_through_api(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        monkeypatch.setattr(settings, "max_upload_bytes", 8)
        _, token = await self._setup_user(db)

        resp = await client.post(
            "/api/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("big.zip", io.BytesIO(b"x" * 100), "application/zip")},
        )

        assert resp.status_code == 413
        assert resp.json()["code"] == FileErr.TOO_LARGE
        assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == []

    async def should_not_persist_record_when_storage_fails(
        self, db: AsyncSession, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings

        store = tmp_path / "store"
        store.mkdir()
        (store / "blocked.txt").write_text("x")
        monkeypatch.setattr(
            settings, "files_store_dir", str(store / "blocked.txt" / "sub")
        )

        user_id = await _user(db)
        with pytest.raises(BizError) as exc:
            await _file(db, uploader_id=user_id)

        assert exc.value.errcode == FileErr.STORE_ERROR
        assert len((await db.execute(select(LibraryFile))).scalars().all()) == 0
