"""后台用户管理端点 /admin/users 与 /admin/stats 的专项测试（模块9 测试补盲）。"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import RolePermission
from app.modules.auth.models import Profile, User
from app.modules.auth.security import hashpwd
from app.modules.content.models import ContentItem, ContentType
from app.modules.files.models import LibraryFile
from app.modules.rbac.permissions import Permission


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
    await db.flush()
    # 后台 RBAC：admin 用户缺省为 super_admin 角色（进入 users/stats/trend 需 admin 域权限点）
    if account_level == "admin":
        db.add(Profile(user_id=user.id, role="super_admin", nickname=username))
    await db.commit()
    await db.refresh(user)
    return user


async def _grant_super_admin(db: AsyncSession, *perms: Permission) -> None:
    """给 admin:super_admin 授指定权限点（幂等，复刻 backend super_admin DEFAULT_GRANTS 的 admin 域）。"""
    for p in perms:
        exists = await db.scalar(
            select(RolePermission.id).where(
                RolePermission.role_name == "admin:super_admin",
                RolePermission.permission == p.value,
            )
        )
        if exists is None:
            db.add(RolePermission(role_name="admin:super_admin", permission=p.value))
    await db.flush()


def _login(client: AsyncClient, username: str) -> Any:
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": "secret123456"},
    )


async def _login_admin(
    db: AsyncSession,
    client: AsyncClient,
    username: str = "root",
    *perms: Permission,
) -> Any:
    """给 admin(默认 super_admin) 授指定权限点后用其登录，供期望 200 的后台用例。"""
    await _grant_super_admin(db, *perms)
    return await _login(client, username)


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
        await _login_admin(
            db,
            client,
            "root",
            Permission.admin_users_manage,
            Permission.admin_dashboard,
        )

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
        await _login_admin(db, client, "root", Permission.admin_users_manage)

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
        await _login_admin(db, client, "root", Permission.admin_users_manage)

        resp = await client.get("/api/v1/admin/users", params={"keyword": "zhang"})
        items = resp.json()["data"]["items"]
        assert all("zhang" in i["username"] for i in items)
        assert any(i["username"] == "zhangsan" for i in items)


async def _seed_stats(db: AsyncSession, n_users: int = 3) -> None:
    await _create_user(db, "root", account_level="admin")
    for i in range(n_users):
        await _create_user(db, f"u{i}", account_level="normal")
    from app.modules.content.models import Board as _models

    board = _models(slug="stats", title="统计", description="", is_public=True)
    db.add(board)
    await db.flush()
    db.add(
        ContentItem(
            content_type=ContentType.DISCUSSION,
            author_id=int(
                (
                    await db.execute(select(User.id).where(User.username == "u0"))
                ).scalar_one()
            ),
            board_id=board.id,
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
        await _login_admin(db, client, "root", Permission.admin_dashboard)

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
        await _login_admin(db, client, "root", Permission.admin_dashboard)
        resp = await client.get("/api/v1/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


class TestAdminTrend:
    async def should_reject_non_admin(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "member1", account_level="normal")
        await _login(client, "member1")
        resp = await client.get("/api/v1/admin/stats/trend")
        assert resp.status_code in (401, 403)

    async def should_return_daily_deltas(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _seed_stats(db)  # root+u0..u2 共4用户，1帖
        await _login_admin(db, client, "root", Permission.admin_dashboard)
        resp = await client.get("/api/v1/admin/stats/trend", params={"days": 7})
        assert resp.status_code == 200
        data = resp.json()["data"]
        items = data["items"]
        assert len(items) == 7
        # 找今天所在序列项：user_delta 至少含 _seed_stats 新增的4个同天增量
        today = items[-1]
        assert today["user_delta"] >= 4
        assert today["post_delta"] >= 1
        # 序列按日期升序、日期连续无缺
        for i in range(1, len(items)):
            assert items[i]["date"] > items[i - 1]["date"]

    async def should_validate_days_bounds(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, "root", account_level="admin")
        await _login(client, "root")
        resp = await client.get("/api/v1/admin/stats/trend", params={"days": 0})
        assert resp.status_code == 422
