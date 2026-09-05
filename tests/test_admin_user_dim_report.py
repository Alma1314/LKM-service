"""M3.B0.3：admin/报表读与 A4 管理读的在线↔离线**边界** 验收。

被测对象是「宽表 read port 是否真读 dim」与「在线管理读是否仍离线隔离、绝不经 dim」这两个
半轴（数据面隔离 B0.3）：

- **边界（管理 read 仍在线）**：把 ``user_dim`` 表**整表 DROP 掉**，再打 A4 实时管理列表
  ``/admin/users`` → 必须仍 200 且返回完整行（证明 A4 list 走 auth 实时缝 + user_dim，绝
  不以 dim 为源；若它偷偷改读 dim，此处必炸 NOT NULL/缺失表）。
- **正测（report read 真读 dim）**：显式 insert 一条 ``UserDim`` 宽表行，经
  ``app.modules.admin.dim_report.list_user_dim`` 读 → 返回该行；``include_pii`` 门控 email
  的带/不带；keyword 过滤与 total 对齐。只读：不产生任何管理/写动作。

落位/不含性：本模块**不发明**新的报表 HTTP 路由（避免在本无独立离线报表消费面的 B0.3 伪造
产品）；也不把 ``/admin/users``/``/admin/stats(/trend)`` 等**在线实时**管理/仪表盘读 repoint
去读 dim（保持实时，杜绝陈旧 actor/陈旧仪表盘）。在线管理列表保持经 ``auth.snapshot`` 缝。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.admin.dim_report as dim_report
import app.modules.auth.models  # noqa: F401  确保 User/Profile 元数据可见
from app.db.model_registry import ensure_all_models
from app.db.user_dim import UserDim
from app.modules.admin.models import RolePermission
from app.modules.auth.models import Profile, User
from app.modules.auth.security import hashpwd
from app.modules.rbac.permissions import Permission


@pytest.fixture
async def _reg() -> AsyncIterator[None]:
    """确保 user_dim 等全量模型注册进 shared Base.metadata（单文件隔离跑也 build dim 表）。"""
    ensure_all_models()
    yield


async def _create_user(
    db: AsyncSession, username: str, *, account_level: str = "local"
) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=await hashpwd("secret123456"),
        account_level=account_level,
    )
    db.add(user)
    await db.flush()
    if account_level == "admin":
        db.add(Profile(user_id=user.id, role="super_admin", nickname=username))
    await db.commit()
    await db.refresh(user)
    return user


async def _grant(db: AsyncSession, *perms: Permission) -> None:
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


async def _login_is_admin(
    client: AsyncClient,
    username: str,
) -> None:
    await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": "secret123456"},
    )


async def _seed_one_admin_dim_row(db: AsyncSession) -> int:
    """建 root(admin) + 一个普通用户，并把该普通用户同步为一条 dim 行（离线镜像当报表读源）。

    注：conftest 会话默认 ``expire_on_commit=True``，commit 后旧 ORM 对象被失效，属性惰性读
    在 async 下会 MissingGreenlet。故每次 create 后**重新 await select 取新鲜对象**再做
    dim 镜像、并在 commit 前捕获纯量 id（永不触碰 post-commit 的过期属性）。
    """
    await _create_user(db, "root", account_level="admin")
    await _create_user(db, "repuser", account_level="local")
    # 重新取新鲜(已进 session 且未过期)的对象，避免 commit 后的惰性重载
    u = (
        await db.execute(select(User).where(User.username == "repuser"))
    ).scalar_one()
    uid: int = int(u.id)  # commit 前捕获纯量，杜绝过期访问
    # 直接 upsert 进离线副本(镜像 user_dim_sync.sync_dim_for_ids 产出的字节列)
    row = UserDim(
        user_id=uid,
        username=str(u.username),
        email=u.email,
        nickname="报表客",
        role="member",
        account_level=u.account_level,
        is_banned=bool(u.is_locked),
        is_locked=u.is_locked,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )
    db.add(row)
    await db.commit()
    return uid


class TestReportReadReadsDim:
    """正测：离线报表 read port 确实读 user_dim（读侧接通 B0.2 填充的数据）。"""

    async def test_list_user_dim_returns_inserted_row(
        self, db: AsyncSession, _reg: None
    ) -> None:
        uid = await _seed_one_admin_dim_row(db)
        rows, total = await dim_report.list_user_dim(db, include_pii=True)
        assert total >= 1
        hit = next(r for r in rows if r.user_id == uid)
        assert hit.username == "repuser"
        assert hit.email == "repuser@example.com"  # PII: include_pii=True 才带
        assert hit.nickname == "报表客"
        assert hit.account_level == "local"
        assert hit.is_banned is False
        assert hit.sync_ts is not None

    async def test_email_hidden_without_pii_gate(
        self, db: AsyncSession, _reg: None
    ) -> None:
        await _seed_one_admin_dim_row(db)
        rows, _ = await dim_report.list_user_dim(db, include_pii=False)
        assert all(r.email is None for r in rows)

    async def test_keyword_filters_and_counts(
        self, db: AsyncSession, _reg: None
    ) -> None:
        await _seed_one_admin_dim_row(db)
        rows, total = await dim_report.list_user_dim(db, q="repuse", include_pii=False)
        assert total >= 1
        assert all("repuse" in r.username for r in rows)


class TestAdminManagementStaysOfflineIsolated:
    """边界：A4 实时管理列表读**绝不可**以 user_dim 为源（在报表隔离下仍实时、经 auth 缝）。"""

    async def test_admin_users_list_survives_dropped_dim_table(
        self, db: AsyncSession, client: AsyncClient, _reg: None
    ) -> None:
        # 树中 A4 管理列表对应唯一消费 auth.list_user_snapshots 的在线路由；
        # 若它被错误 repoint 到 dim，本用例(dim 整表 DROP)必失败 → 证明未被 repoint。
        await _create_user(db, "root", account_level="admin")
        # 再造一个普通用户让管理列表有行可断言（在线实时源，与 dim 无关）
        await _create_user(db, "alice", account_level="local")
        await _grant(db, Permission.admin_users_manage)
        await _login_is_admin(client, "root")

        # drop 掉整个离线宽表：任何经 dim 的读此刻都会抛 → 若 A4 列表碰 dim 则此处崩
        await db.execute(text("DROP TABLE IF EXISTS user_dim"))
        await db.commit()

        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] >= 2  # root + alice（在线实时源，非 dim）
        assert any(i["username"] == "alice" for i in body["items"])

    async def test_management_list_pii_gate_untouched_by_dim(
        self, db: AsyncSession, client: AsyncClient, _reg: None
    ) -> None:
        # include_pii 仍是在线实时列表的能力（非 PII dim 侧路由），A4 功能不因 dim 而改
        await _create_user(db, "root", account_level="admin")
        await _create_user(db, "alice", account_level="local")
        await _grant(db, Permission.admin_users_manage)
        await _login_is_admin(client, "root")

        resp = await client.get("/api/v1/admin/users", params={"include_pii": "true"})
        assert resp.status_code == 200
        alice = next(i for i in resp.json()["data"]["items"] if i["username"] == "alice")
        assert alice["email"] == "alice@example.com"
