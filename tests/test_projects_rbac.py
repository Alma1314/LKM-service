"""projects 迁移 RBAC：申请提交/审核 权限点接线测试。

申请端点（submit_app）从旧 RequireLevel("normal") 收紧为 RequirePermission(projects_application_create)，
故普通 member 未授权限时现应 403（先前 200，呈现收紧）；审核端点（review_app）走
require_admin_2fa（危险操作 2FA，读 cookie），故审核用例需以 create_admin_access_token(mfa_verified=True)
写入 client cookie 才能越 2FA 门槛，从而触达 handler 内 projects_application_review 权限点判定。
"""

from sqlalchemy import select

from app.db.models import Profile, ProjectApplication, RolePermission, User
from app.modules.admin.deps import COOKIE_NAME, COOKIE_PATH, create_admin_access_token
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


async def _mk_user(
    db: DB, uname: str, level: str = "normal", role: str = "member"
) -> User:
    # users.hashed_password 为 NOT NULL，传占位值；Profile 列是 nickname（无 display_name）。
    user = User(
        username=uname,
        account_level=level,
        hashed_password="rbac-test-placeholder-not-a-real-hash",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, role=role, nickname=uname))
    await db.flush()
    return user


async def _seed_perm(db: DB, role: str, perm: str) -> None:
    # 幂等：判存在再插，避免撞 role_permissions 唯一约束。
    exists = await db.scalar(
        select(RolePermission.id).where(
            RolePermission.role_name == role,
            RolePermission.permission == perm,
        )
    )
    if exists is None:
        db.add(RolePermission(role_name=role, permission=perm))
        await db.flush()


def _headers(user: User, role: str = "member") -> dict[str, str]:
    # create_access_token 的 role 是必填参数（见 security.py:61）。CurrentUser.role 来自 DB
    # profile.role，token 里 role 仅占位（解析时以 DB profile.role 覆盖）。
    tok = create_access_token(
        user_id=user.id, account_level=user.account_level, role=role
    )
    return {"Authorization": f"Bearer {tok}"}


def _set_admin_mfa_cookie(client: Client, user: User) -> None:
    # 审核端点 require_admin_2fa 从 cookie 读后台 access token 且须 mfa_verified 信任。
    tok = create_admin_access_token(user, mfa_verified=True)
    client.cookies.set(COOKIE_NAME, tok, path=COOKIE_PATH)


def _app_payload(title: str = "LKM") -> dict[str, object]:
    return {
        "title": title,
        "summary": "s",
        "description": "d",
        "member_claims": [
            {"display_name": "艾尔", "role_in_project": "组长", "user_id": None}
        ],
    }


class TestSubmitAppPermission:
    async def test_member_without_grant_cannot_submit(
        self, db: DB, client: Client
    ) -> None:
        # member（normal/member，未授 projects_application_create）提交 → 403（收紧证明）
        u = await _mk_user(db, "m0", level="normal", role="member")
        r = await client.post(
            "/api/v1/projects/applications", headers=_headers(u), json=_app_payload()
        )
        assert r.status_code == 403

    async def test_member_with_grant_can_submit(self, db: DB, client: Client) -> None:
        # 授 projects_application_create 的普通用户提交 → 200
        await _seed_perm(db, "normal:member", "projects.application_create")
        u = await _mk_user(db, "m1", level="normal", role="member")
        r = await client.post(
            "/api/v1/projects/applications", headers=_headers(u), json=_app_payload()
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "pending"

    async def test_no_auth_rejected(self, db: DB, client: Client) -> None:
        # 未登录 → 403
        r = await client.post("/api/v1/projects/applications", json=_app_payload())
        assert r.status_code == 403


class TestReviewAppPermission:
    async def test_org_member_cannot_review(self, db: DB, client: Client) -> None:
        # org_member 未授 projects_application_review → 越 2FA 门槛后 403
        await _seed_perm(db, "admin:org_member", "projects.application_create")
        u = await _mk_user(db, "org0", level="admin", role="org_member")
        db.add(
            ProjectApplication(
                applicant_id=u.id,
                title="t",
                summary="s",
                description="d",
                member_claims="[]",
                status="pending",
            )
        )
        await db.flush()
        app_id = await db.scalar(select(ProjectApplication.id))
        _set_admin_mfa_cookie(client, u)
        r = await client.post(
            f"/api/v1/projects/applications/{app_id}/review", json={"approve": True}
        )
        assert r.status_code == 403

    async def test_super_admin_can_review(self, db: DB, client: Client) -> None:
        # super_admin 授 projects_application_review → 审核通过 200
        await _seed_perm(db, "admin:super_admin", "projects.application_review")
        u = await _mk_user(db, "sadmin", level="admin", role="super_admin")
        db.add(
            ProjectApplication(
                applicant_id=u.id,
                title="t",
                summary="s",
                description="d",
                member_claims="[]",
                status="pending",
            )
        )
        await db.flush()
        app_id = await db.scalar(select(ProjectApplication.id))
        _set_admin_mfa_cookie(client, u)
        r = await client.post(
            f"/api/v1/projects/applications/{app_id}/review", json={"approve": True}
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "approved"

    async def test_review_without_2fa_blocked(self, db: DB, client: Client) -> None:
        # 无 2FA 信任 cookie → 2FA 门槛拦截（MFA_REQUIRED → 401/403 依据 require_admin_2fa 行为）
        await _seed_perm(db, "admin:super_admin", "projects.application_review")
        u = await _mk_user(db, "no2fa", level="admin", role="super_admin")
        db.add(
            ProjectApplication(
                applicant_id=u.id,
                title="t",
                summary="s",
                description="d",
                member_claims="[]",
                status="pending",
            )
        )
        await db.flush()
        app_id = await db.scalar(select(ProjectApplication.id))
        # 注意：不 set 2FA cookie
        r = await client.post(
            f"/api/v1/projects/applications/{app_id}/review", json={"approve": True}
        )
        assert r.status_code in (401, 403, 428)
