"""后台管理系统 cookie 会话认证的 HTTP 集成测试。

覆盖：登录(成功/非 admin 拒绝/凭证错)、带 cookie 访问 /me、无 cookie 拒绝、
      refresh 换新 access、logout 清会话。遵循 conftest 的 db+client 内存库模式。
"""

import datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile, RolePermission, User
from app.modules.auth.models import RefreshToken
from app.modules.auth.security import hashpwd
from app.modules.rbac.permissions import Permission


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
    await db.flush()
    # 后台 RBAC：admin 用户缺省为 super_admin 角色（/me/数据/删除端点需 admin 域权限点）
    if account_level == "admin":
        db.add(Profile(user_id=user.id, role="super_admin", nickname=username))
    await db.commit()
    await db.refresh(user)
    return user


async def _grant(db: AsyncSession, perm: Permission) -> None:
    """给 admin:super_admin 授指定权限点（幂等，复刻 super_admin DEFAULT_GRANTS）。"""
    exists = await db.scalar(
        select(RolePermission.id).where(
            RolePermission.role_name == "admin:super_admin",
            RolePermission.permission == perm.value,
        )
    )
    if exists is None:
        db.add(RolePermission(role_name="admin:super_admin", permission=perm.value))
    await db.flush()


def _login(
    client: AsyncClient, username: str = "root", password: str = "secret123456"
) -> Any:
    """用客户端登录，返回响应。httpx 会把 Set-Cookie 自动持久化到 client.cookies。"""
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": password},
    )


# ===================================================================
# 登录
# ===================================================================


class TestAdminLogin:
    async def should_login_admin_and_set_cookies(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="root", account_level="admin")
        resp = await _login(client, "root")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["code"] == 0
        assert body["data"]["account_level"] == "admin"
        # httpx 已把 Set-Cookie 持久化到客户端 jar
        assert client.cookies.get("admin_session")
        assert client.cookies.get("admin_refresh")

    async def should_reject_wrong_password(self, db: AsyncSession, client: AsyncClient):
        await _create_user(db, username="root", account_level="admin")
        resp = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": "root", "password": "wrong-pass"},
        )
        assert resp.status_code == 403

    async def should_reject_non_admin_account(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="member1", account_level="normal")
        resp = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": "member1", "password": "secret123456"},
        )
        assert resp.status_code == 403
        # 即使密码正确，普通用户不得进后台
        body: dict[str, Any] = resp.json()
        assert body["msg"] == "无后台访问权限"

    async def should_reject_unknown_username(
        self, db: AsyncSession, client: AsyncClient
    ):
        resp = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": "ghost", "password": "secret123456"},
        )
        assert resp.status_code == 403

    async def should_store_admin_refresh_with_kind(
        self, db: AsyncSession, client: AsyncClient
    ):
        """后台登录生成的 refresh 令牌必须落库为 kind='admin'（与前台 web 隔离）。"""
        await _create_user(db, username="kind1", account_level="admin")
        login = await _login(client, "kind1")
        assert login.status_code == 200
        stored = (await db.execute(select(RefreshToken))).scalars().first()
        assert stored is not None
        assert stored.kind == "admin"

    async def should_reject_web_refresh_in_admin_endpoint(
        self, db: AsyncSession, client: AsyncClient
    ):
        """前台(web) refresh 令牌不得在后台刷新端点被消费（隔离后方，防跨会话互用）。"""
        await _create_user(db, username="kind2", account_level="admin")
        # 直接插入一条 kind='web' 的 refresh，验证后台端点拒绝
        kind2: User | None = (
            (await db.execute(select(User).where(User.username == "kind2")))
            .scalars()
            .first()
        )
        assert kind2 is not None
        db.add(
            RefreshToken(
                user_id=kind2.id,
                token_hash=(await hashpwd("not-a-real-token"))[0:64],
                kind="web",
                mfa_verified=False,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(days=1),
                revoked_at=None,
            )
        )
        await db.commit()
        resp = await client.post("/api/v1/admin/auth/refresh")
        # 无 admin refresh cookie → 403
        assert resp.status_code == 403


# ===================================================================
# /me 访问控制
# ===================================================================


class TestAdminMe:
    async def should_reject_without_cookie(self, db: AsyncSession, client: AsyncClient):
        resp = await client.get("/api/v1/admin/auth/me")
        assert resp.status_code == 403

    async def should_allow_admin_with_access_cookie(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="root", account_level="admin")
        await _grant(db, Permission.admin_dashboard)
        login = await _login(client, "root")
        assert login.status_code == 200
        assert client.cookies.get("admin_session")

        # 登录后 Set-Cookie 已持久化，同一 client 自动携带，无需手传
        resp = await client.get("/api/v1/admin/auth/me")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["code"] == 0
        assert body["data"]["account_level"] == "admin"


# ===================================================================
# refresh / logout
# ===================================================================


class TestAdminRefreshAndLogout:
    async def should_rotate_on_refresh(self, db: AsyncSession, client: AsyncClient):
        await _create_user(db, username="root", account_level="admin")
        login = await _login(client, "root")
        assert login.status_code == 200

        # 用已持久化的 refresh cookie 换新 access + 新 refresh
        resp = await client.post("/api/v1/admin/auth/refresh")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert body["code"] == 0

    async def should_logout_and_clear(self, db: AsyncSession, client: AsyncClient):
        await _create_user(db, username="root", account_level="admin")
        login = await _login(client, "root")
        assert login.status_code == 200

        logout = await client.post("/api/v1/admin/auth/logout")
        assert logout.status_code == 200

        # 登出后旧 refresh 已被撤销，再用其刷新 → 应被拒
        # （httpx jar 里 cookie 已清，需手动塞回旧值验证撤销）
        again = await client.post("/api/v1/admin/auth/refresh")
        assert again.status_code == 403

    async def should_reject_reuse_of_old_refresh_after_rotation(
        self, db: AsyncSession, client: AsyncClient
    ):
        # 用独特用户名避开共享内存 admin 登录限流（5 次/300s）在本进程跨用例累计
        await _create_user(db, username="root_reuse", account_level="admin")
        login = await _login(client, "root_reuse")
        assert login.status_code == 200

        old_refresh = client.cookies.get("admin_refresh")
        assert old_refresh

        first = await client.post("/api/v1/admin/auth/refresh")
        assert first.status_code == 200

        # 旋转后，旧 refresh 已撤销：清掉旋转后写下的新 cookie（及历史遗留），
        # 塞回旧值再刷新应被拒。cookie path 须与实际写入的 COOKIE_PATH（/api/v1）一致，
        # 否则 httpx 会按最具体 path 优先发送旋转后的新 cookie，导致测不到旧值复用。
        for cp in ("/api/v1", "/api/v1/admin"):
            client.cookies.delete("admin_refresh", path=cp)
        client.cookies.set("admin_refresh", old_refresh, path="/api/v1")
        again = await client.post("/api/v1/admin/auth/refresh")
        assert again.status_code == 403


# ===================================================================
# 用户列表 / 统计（require_admin 保护）
# ===================================================================


class TestAdminData:
    async def should_reject_without_cookie(self, db: AsyncSession, client: AsyncClient):
        assert (await client.get("/api/v1/admin/users")).status_code == 403
        assert (await client.get("/api/v1/admin/stats")).status_code == 403

    async def should_list_users_hiding_pii_by_default(
        self, db: AsyncSession, client: AsyncClient
    ):
        # 用不重复用户名，避开共享内存 rate limiter 对本进程"admin 用户名登录次数"的计数
        await _create_user(db, username="data_root1", account_level="admin")
        await _create_user(db, username="member_1", account_level="normal")
        await _grant(db, Permission.admin_users_manage)
        await _login(client, "data_root1")

        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        data: dict[str, Any] = body["data"]
        assert data["total"] == 2
        items: list[Any] = data["items"]
        names = {it["username"] for it in items}
        assert names == {"data_root1", "member_1"}
        # 默认不返回邮箱（PII 隐藏）
        assert all(it["email"] is None for it in items)

    async def should_include_pii_when_requested(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="data_root2", account_level="admin")
        await _grant(db, Permission.admin_users_manage)
        await _login(client, "data_root2")
        resp = await client.get("/api/v1/admin/users", params={"include_pii": "true"})
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        data: dict[str, Any] = body["data"]
        items: list[Any] = data["items"]
        email = next(
            (it["email"] for it in items if it["username"] == "data_root2"), None
        )
        assert email == "data_root2@example.com"

    async def should_filter_users_by_keyword(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="data_root3", account_level="admin")
        await _create_user(db, username="other", account_level="normal")
        await _grant(db, Permission.admin_users_manage)
        await _login(client, "data_root3")
        resp = await client.get("/api/v1/admin/users", params={"keyword": "data_root"})
        body: dict[str, Any] = resp.json()
        data: dict[str, Any] = body["data"]
        assert data["total"] == 1
        assert data["items"][0]["username"] == "data_root3"

    async def should_return_stats(self, db: AsyncSession, client: AsyncClient):
        await _create_user(db, username="data_root4", account_level="admin")
        await _grant(db, Permission.admin_dashboard)
        await _login(client, "data_root4")
        resp = await client.get("/api/v1/admin/stats")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        data: dict[str, Any] = body["data"]
        assert data["user_count"] >= 1
        assert data["post_count"] == 0
        assert data["file_count"] == 0


# ===================================================================
# get_real_client_ip：不信任客户端伪造的 XFF（防绕过 IP 级限流）
# ===================================================================


class TestGetRealClientIp:
    def should_not_trust_spoofed_xff(self):
        """伪造 X-Forwarded-For 不应改变取到的 IP——应用层不手动信 XFF，依赖 uvicorn proxy-headers。"""
        from starlette.requests import Request as StarletteRequest

        scope: dict[str, Any] = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/auth/login",
            "headers": [(b"x-forwarded-for", b"1.2.3.4")],
            "client": ("9.9.9.9", 12345),
            "scheme": "http",
            "query_string": b"",
            "server": ("testserver", 80),
        }
        req = StarletteRequest(scope)
        from app.modules.admin.deps import get_real_client_ip

        # 即使带了伪造 XFF，也应返回真实 client.host，而非 1.2.3.4
        assert get_real_client_ip(req) == "9.9.9.9"

    def should_return_unknown_without_client(self):
        """client 缺失时回退 'unknown'，不崩溃。"""
        from starlette.requests import Request as StarletteRequest

        scope: dict[str, Any] = {
            "type": "http",
            "method": "POST",
            "path": "/x",
            "headers": [],
            "client": None,
            "scheme": "http",
            "query_string": b"",
            "server": ("testserver", 80),
        }
        req = StarletteRequest(scope)
        from app.modules.admin.deps import get_real_client_ip

        assert get_real_client_ip(req) == "unknown"


# ===================================================================
# 改密撤销：updated_at 晚于 token iat 时旧 admin cookie 应失效（与前台一致）
# ===================================================================


class TestAdminPasswordChangeInvalidation:
    async def should_invalidate_old_cookie_after_password_change(
        self, db: AsyncSession, client: AsyncClient
    ):
        await _create_user(db, username="root_pwd", account_level="admin")
        login = await _login(client, "root_pwd")
        assert login.status_code == 200
        assert client.cookies.get("admin_session")

        user = (
            (await db.execute(select(User).where(User.username == "root_pwd")))
            .scalars()
            .first()
        )
        assert user is not None
        # 模拟改密：updated_at 晚于 token 签发时间（iat）超过 5 秒容差
        user.updated_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=10
        )
        await db.commit()

        resp = await client.get("/api/v1/admin/auth/me")
        assert resp.status_code == 403


# ===================================================================
# 管理员删除用户内容：require_admin_2fa 门禁（未 step-up → 401 code=4）
# ===================================================================


def _totp_code_now(secret: str) -> str:
    """生成当前时间步的 TOTP 6 位码（与 security.verify_totp window=1 对齐）。"""
    import base64
    import hashlib
    import hmac
    import struct
    import time

    key = base64.b32decode(secret, casefold=True)
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (
        struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    ) % 1_000_000
    return f"{code:06d}"


class TestAdminContentDelete:
    """DELETE /admin/content/* —— 危险写操作必须持有后台 2FA 信任。"""

    async def _enable_admin_totp(self, db: AsyncSession, user_id: int) -> str:
        """给管理员建一个已启用 TOTP 记录，返回明文 secret。"""
        from app.modules.auth.models import TOTP
        from app.modules.auth.security import encrypt_secret, generate_totp_secret

        secret = generate_totp_secret()
        db.add(TOTP(user_id=user_id, secret=encrypt_secret(secret), enabled=True))
        await db.commit()
        return secret

    async def should_gate_without_2fa(self, db: AsyncSession, client: AsyncClient):
        """未做 step-up 的 admin 会话调删除 → 401 code=4（MFA_REQUIRED）。"""
        await _create_user(db, username="adm_del", account_level="admin")
        login = await _login(client, "adm_del")
        assert login.status_code == 200

        resp = await client.delete("/api/v1/admin/content/item/99999")
        assert resp.status_code == 401
        assert resp.json()["code"] == 4  # CommonErr.MFA_REQUIRED

    async def should_pass_gate_after_stepup(
        self, db: AsyncSession, client: AsyncClient
    ):
        """完成 admin step-up（POST /admin/auth/2fa）后，删除能走到 service（不存在的帖→404）。"""
        await _create_user(db, username="adm_del2", account_level="admin")
        await _grant(db, Permission.admin_content_review)
        login = await _login(client, "adm_del2")
        assert login.status_code == 200

        user = (
            (await db.execute(select(User).where(User.username == "adm_del2")))
            .scalars()
            .first()
        )
        secret = await self._enable_admin_totp(db, user.id)
        stepup = await client.post(
            "/api/v1/admin/auth/2fa", json={"code": _totp_code_now(secret)}
        )
        assert stepup.status_code == 200

        # 已带 2FA 信任：删除不存在的内容项应到达 service 层 → 404 CONTENT_NOT_FOUND，而非 401
        resp = await client.delete("/api/v1/admin/content/item/99999")
        assert resp.status_code == 404
