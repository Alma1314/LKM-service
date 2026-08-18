"""后台用户管理端点 /admin/users 与 /admin/stats 的专项测试（模块9 测试补盲）。"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ForumPost, LibraryFile, User
from app.modules.auth.security import hashpwd


async def _create_user(
    db: AsyncSession,
    username: str,
    account_level: str = "local",
    email: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        hashed_password=await hashpwd("secret123456"),
        account_level=account_level,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _login(client: AsyncClient, username: str) -> Any:
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": "secret123456"},
    )


class TestAdminUsersList:
    async def should_reject_non_admin(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "member1", account_level="normal")
        await _login(client, "member1")
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code in (401, 403)

    async def should_list_users_preview_without_pii(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "root", account_level="admin")
        await _create_user(db, "alice", account_level="normal", email="a@priv.io")
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] >= 2
        # PII 默认隐藏：email/phone 为 None
        alice = next(i for i in body["items"] if i["username"] == "alice")
        assert alice["email"] is None
        assert alice["phone"] is None
        assert alice["is_locked"] is False
        assert alice["account_level"] == "normal"

    async def should_include_pii_when_requested(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "root", account_level="admin")
        await _create_user(db, "bob", account_level="normal", email="bob@priv.io")
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/users", params={"include_pii": "true"})
        assert resp.status_code == 200
        bob = next(i for i in resp.json()["data"]["items"] if i["username"] == "bob")
        assert bob["email"] == "bob@priv.io"

    async def should_filter_users_by_keyword(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "root", account_level="admin")
        await _create_user(db, "zhangsan", account_level="normal")
        await _create_user(db, "lisi", account_level="normal")
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/users", params={"keyword": "zhang"})
        items = resp.json()["data"]["items"]
        assert all("zhang" in i["username"] for i in items)
        assert any(i["username"] == "zhangsan" for i in items)


async def _seed_stats(db: AsyncSession, n_users: int = 3) -> None:
    await _create_user(db, "root", account_level="admin")
    for i in range(n_users):
        await _create_user(db, f"u{i}", account_level="normal")
    db.add(
        ForumPost(
            author_id=int(
                (
                    await db.execute(select(User.id).where(User.username == "u0"))
                ).scalar_one()
            ),
            category_id="cat",
            title="t",
            excerpt="",
            content="c",
            tags="[]",
        )
    )
    db.add(
        LibraryFile(
            uploader_id=int(
                (
                    await db.execute(select(User.id).where(User.username == "u1"))
                ).scalar_one()
            ),
            original_name="f.pdf",
            stored_name="f.pdf",
            mime_type="application/pdf",
            size=10,
            status="pending",
        )
    )
    await db.commit()


class TestAdminStats:
    async def should_aggregate_counts(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _seed_stats(db)
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["user_count"] >= 4  # root + u0..u2
        assert data["post_count"] >= 1
        assert data["file_count"] >= 1
        assert data["file_pending_count"] >= 1

    async def should_be_tolerant_of_missing_tables(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        """单表不可用时统计不整体抛 500（_safe_count 兜底）。"""
        await _create_user(db, "root", account_level="admin")
        await _login(client, "root")
        resp = await client.get("/api/v1/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
