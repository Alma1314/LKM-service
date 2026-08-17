"""后台举报列表端点 /admin/reports 的 HTTP 集成测试。

覆盖：非 admin 拒绝、admin 登录后列表返回、按 status 过滤、空列表。遵循 conftest 的 db+client 模式。
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Report, User
from app.modules.auth.security import hashpwd


async def _create_user(
    db: AsyncSession,
    username: str,
    password: str = "secret123456",
    account_level: str = "local",
) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=await hashpwd(password),
        account_level=account_level,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _login(client: AsyncClient, username: str) -> Any:
    """发起后台登录请求；httpx 会把 Set-Cookie 持久化到 client.cookies。"""
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": "secret123456"},
    )


async def _seed_reports(db: AsyncSession) -> None:
    db.add_all(
        [
            Report(
                type="post",
                target_id="post-1",
                target_title="垃圾广告帖",
                reporter_name="A",
                reason="营销推广",
                status="pending",
            ),
            Report(
                type="comment",
                target_id="post-2",
                target_title="恶意评论",
                reporter_name="B",
                reason="人身攻击",
                status="pending",
            ),
            Report(
                type="file",
                target_id="file-7",
                target_title="版权文件",
                reporter_name="C",
                reason="版权",
                status="resolved",
            ),
        ]
    )
    await db.commit()


class TestAdminReports:
    async def should_reject_non_admin(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, username="member1", account_level="normal")
        await _login(client, "member1")
        resp = await client.get("/api/v1/admin/reports")
        assert resp.status_code in (401, 403)

    async def should_list_reports_for_admin(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, username="root", account_level="admin")
        await _seed_reports(db)
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/reports")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["code"] == 0
        assert body["data"]["total"] == 3
        assert len(body["data"]["items"]) == 3
        first = body["data"]["items"][0]
        assert set(first.keys()) >= {
            "id",
            "type",
            "target_id",
            "target_title",
            "reporter_name",
            "reason",
            "status",
        }

    async def should_filter_reports_by_status(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, username="root", account_level="admin")
        await _seed_reports(db)
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/reports", params={"status": "pending"})
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["data"]["total"] == 2
        assert all(item["status"] == "pending" for item in body["data"]["items"])

    async def should_return_empty_when_no_reports(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        await _create_user(db, username="root", account_level="admin")
        await _login(client, "root")

        resp = await client.get("/api/v1/admin/reports")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []
