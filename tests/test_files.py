import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.modules.auth.models
from app.core.err import BizError, CommonErr
from app.db.models import Base, LibraryFile, Profile, User
from app.db.session import get_session
from app.main import app
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.files.errors import FileErr
from app.modules.files.schemas import FileCreate
from app.modules.files.service import (
    bump_download,
    create_file,
    get_file,
    list_files,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))

    def override_get_session():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _user(db, username="alice", email="alice@example.com", nickname=None):
    user = User(
        username=username,
        email=email,
        hashed_password=hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, nickname=nickname))
    db.flush()
    return user.id


def _file(db, uploader_id=1, original_name="讲义.pdf", category_id="math", tags=("数学",)):
    return create_file(
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
    def should_create_file_with_nickname(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db, nickname="爱丽丝")

        f = _file(db, uploader_id=user_id)

        assert f.id == 1
        assert f.uploader_id == user_id
        assert f.uploader_name == "爱丽丝"
        assert f.tags == ["数学"]
        assert f.status == "pending"
        assert f.download_count == 0
        assert f.view_count == 0
        stored = db.query(LibraryFile).filter(LibraryFile.id == f.id).one()
        assert (tmp_path / stored.stored_name).read_bytes() == b"%PDF-1.4 fake content"

    def should_use_username_when_no_nickname(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db, username="bob", email="bob@example.com")

        f = _file(db, uploader_id=user_id)

        assert f.uploader_name == "bob"

    def should_list_files_paginated(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)
        _file(db, uploader_id=user_id, original_name="文件一.pdf")
        _file(db, uploader_id=user_id, original_name="文件二.pdf")

        page = list_files(db, page=1, limit=1)

        assert page.total == 2
        assert page.pages == 2
        assert len(page.items) == 1
        assert page.items[0].original_name == "文件二.pdf"

    def should_filter_files_by_category(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)
        _file(db, uploader_id=user_id, category_id="math")
        _file(db, uploader_id=user_id, original_name="物理题.pdf", category_id="physics")

        page = list_files(db, category_id="math")

        assert page.total == 1
        assert page.items[0].category_id == "math"

    def should_sort_by_downloads(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)
        hot = _file(db, uploader_id=user_id, original_name="热门.zip")
        cold = _file(db, uploader_id=user_id, original_name="冷门.pdf")
        bump_download(db, hot.id)
        bump_download(db, hot.id)

        page = list_files(db, sort="downloads")

        assert [f.original_name for f in page.items] == ["热门.zip", "冷门.pdf"]

    def should_get_file_and_bump_view(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)
        f = _file(db, uploader_id=user_id)

        first = get_file(db, f.id, bump_view=True)
        second = get_file(db, f.id, bump_view=True)

        assert first.view_count == 1
        assert second.view_count == 2

    def should_reject_nonexistent_file(self, db):
        with pytest.raises(BizError) as exc:
            get_file(db, 999)

        assert exc.value.errcode == FileErr.NOT_FOUND

    def should_increment_download(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)
        f = _file(db, uploader_id=user_id)

        assert bump_download(db, f.id) == 1
        assert bump_download(db, f.id) == 2

    def should_reject_upload_over_limit(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)

        with pytest.raises(BizError) as exc:
            create_file(
                db,
                user_id,
                FileCreate(original_name="超大.zip", mime_type="application/zip"),
                stream=io.BytesIO(b"x" * 10),
                max_bytes=5,
            )

        assert exc.value.errcode == FileErr.TOO_LARGE
        assert db.query(LibraryFile).count() == 0
        assert list(tmp_path.iterdir()) == []

    def should_accept_upload_at_exact_limit(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        user_id = _user(db)

        f = create_file(
            db,
            user_id,
            FileCreate(original_name="正好.zip", mime_type="application/zip"),
            stream=io.BytesIO(b"x" * 5),
            max_bytes=5,
        )

        assert f.size == 5


class TestFilesRoutes:
    def _setup_user(self, db, username="tester", email="tester@example.com"):
        user_id = _user(db, username=username, email=email)
        token = create_access_token(user_id=user_id, account_level="normal", role="member")
        return user_id, token

    def _upload(self, client, token, original_name="讲义.pdf", category_id="math"):
        return client.post(
            "/api/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (original_name, io.BytesIO(b"%PDF-1.4 content"), "application/pdf")},
            data={"category_id": category_id, "description": "测试上传", "tags": '["数学"]'},
        )

    def should_reject_upload_without_auth(self, client, db):
        self._setup_user(db)
        resp = client.post(
            "/api/v1/files",
            files={"file": ("a.pdf", io.BytesIO(b"content"), "application/pdf")},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN

    def should_upload_file_with_token(self, client, db):
        user_id, token = self._setup_user(db)
        resp = self._upload(client, token)

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        data = resp.json()["data"]
        assert data["uploader_id"] == user_id
        assert data["original_name"] == "讲义.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size"] == len(b"%PDF-1.4 content")
        assert data["status"] == "pending"
        assert data["tags"] == ["数学"]

    def should_list_files_publicly(self, client, db):
        _, token = self._setup_user(db)
        self._upload(client, token, original_name="公开资料.zip")

        resp = client.get("/api/v1/files")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["original_name"] == "公开资料.zip"

    def should_get_file_detail(self, client, db):
        _, token = self._setup_user(db)
        created = self._upload(client, token).json()["data"]
        file_id = created["id"]

        resp = client.get(f"/api/v1/files/{file_id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["view_count"] == 1

    def should_increment_download_through_api(self, client, db):
        _, token = self._setup_user(db)
        created = self._upload(client, token).json()["data"]
        file_id = created["id"]

        resp = client.post(
            f"/api/v1/files/{file_id}/download",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["download_count"] == 1

    def should_reject_nonexistent_file_detail(self, client, db):
        resp = client.get("/api/v1/files/999")

        assert resp.status_code == 404
        assert resp.json()["code"] == FileErr.NOT_FOUND

    def should_reject_oversized_upload_through_api(self, client, db, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
        monkeypatch.setattr(settings, "max_upload_bytes", 8)
        _, token = self._setup_user(db)

        resp = client.post(
            "/api/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("big.zip", io.BytesIO(b"x" * 100), "application/zip")},
        )

        assert resp.status_code == 413
        assert resp.json()["code"] == FileErr.TOO_LARGE
        assert list(tmp_path.iterdir()) == []

    def should_not_persist_record_when_storage_fails(self, db, tmp_path, monkeypatch):
        from app.core.config import settings

        store = tmp_path / "store"
        store.mkdir()
        (store / "blocked.txt").write_text("x")
        monkeypatch.setattr(settings, "files_store_dir", str(store / "blocked.txt" / "sub"))

        user_id = _user(db)
        with pytest.raises(BizError) as exc:
            _file(db, uploader_id=user_id)

        assert exc.value.errcode == FileErr.STORE_ERROR
        assert db.query(LibraryFile).count() == 0
