"""columns 迁移 RBAC：申请/审核/发布属主。"""

from app.db.models import Column, Profile, RolePermission, User
from app.modules.admin.deps import COOKIE_NAME, COOKIE_PATH, create_admin_access_token
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


async def _mk_user(
    db: DB, uname: str, level: str = "normal", role: str = "member"
) -> User:
    # hashed_password 为 NOT NULL；Profile 列是 nickname（无 display_name）。
    u = User(
        username=uname,
        account_level=level,
        hashed_password="rbac-test-placeholder-not-a-real-hash",
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, role=role, nickname=uname))
    await db.flush()
    return u


def _h(u: User, role: str = "member") -> dict[str, str]:
    # create_access_token 的 role 是必填（security.py:61）；CurrentUser.role 来自 DB profile.role。
    tok = create_access_token(user_id=u.id, account_level=u.account_level, role=role)
    return {"Authorization": f"Bearer {tok}"}


async def test_member_can_apply(db: DB, client: Client) -> None:
    db.add(
        RolePermission(
            role_name="normal:member", permission="columns.application_create"
        )
    )
    await db.flush()
    u = await _mk_user(db, "cm", level="normal", role="member")
    r = await client.post(
        "/api/v1/content/columns/applications",
        headers=_h(u),
        json={"title": "t", "description": "d", "reason": "r"},
    )
    assert r.status_code in (200, 201)


async def test_foreign_cannot_publish_to_other_column(db: DB, client: Client) -> None:
    # 注意：other 有 columns.publish（可发文）但【不授】column.owner_publish
    # （owner 权限仅 super_admin 持有）。若授了 column.owner_publish，check_owner
    # 会因拥有该权限点放行 → 200 而非 403，测试失真。
    db.add(RolePermission(role_name="normal:columnist", permission="columns.publish"))
    await db.flush()
    owner = await _mk_user(db, "col_owner", level="normal", role="columnist")
    other = await _mk_user(db, "col_other", level="normal", role="columnist")
    col = Column(slug="c1", title="C", description="", owner_id=owner.id)
    db.add(col)
    await db.flush()
    r = await client.post(
        f"/api/v1/content/columns/{col.id}/posts",
        headers=_h(other),
        json={"title": "t", "content": "c", "category": "x"},
    )
    assert r.status_code == 403


async def test_owner_can_publish_to_own_column(db: DB, client: Client) -> None:
    # 属主本人（有 columns.publish，无 owner 权限点）走 id_field 属主判定放行。
    db.add(RolePermission(role_name="normal:columnist", permission="columns.publish"))
    await db.flush()
    owner = await _mk_user(db, "cowner", level="normal", role="columnist")
    col = Column(slug="c2", title="C2", description="", owner_id=owner.id)
    db.add(col)
    await db.flush()
    r = await client.post(
        f"/api/v1/content/columns/{col.id}/posts",
        headers=_h(owner),
        json={"title": "t", "content": "c", "category": "x"},
    )
    assert r.status_code in (200, 201)


async def _mk_super_admin(db: DB, uname: str) -> User:
    u = User(
        username=uname,
        account_level="admin",
        hashed_password="rbac-test-placeholder-not-a-real-hash",
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, role="super_admin", nickname=uname))
    await db.flush()
    return u


async def _grant(db: DB, role_name: str, *perms: str) -> None:
    for p in perms:
        db.add(RolePermission(role_name=role_name, permission=p))
    await db.flush()


def _set_admin_mfa_cookie(client: Client, user: User) -> None:
    # review 端点走 require_admin_2fa（后台 cookie + step-up 2FA 信任），
    # 故用后台 access token（mfa_verified=True）写入 client cookie 越过 2FA 门槛，
    # 才触达 handler 内 columns.application_review 权限点判定。与 boards/projects 审核测试一致。
    tok = create_admin_access_token(user, mfa_verified=True)
    client.cookies.set(COOKIE_NAME, tok, path=COOKIE_PATH)


async def test_super_admin_can_review_application(db: DB, client: Client) -> None:
    from app.db.models import ColumnApplication

    # 申请人普通，super_admin 审核（2FA 门槛 + columns.application_review 权限点）。
    applicant = await _mk_user(db, "app_owner", level="normal", role="member")
    await _grant(db, "admin:super_admin", "columns.application_review")
    u = await _mk_user(db, "cap_member", level="admin", role="super_admin")
    db.add(
        ColumnApplication(user_id=applicant.id, title="t", description="d", reason="r")
    )
    await db.flush()
    _set_admin_mfa_cookie(client, u)
    r = await client.post(
        "/api/v1/content/columns/applications/1/review",
        json={"status": "approved"},
    )
    assert r.status_code in (200, 201)


async def test_member_without_apply_perm_is_403(db: DB, client: Client) -> None:
    # 旧代码 apply_column 无权限校验，member 提交任意通过 200；迁移后需
    # columns.application_create。本用例故意【不授】该权限点，锁定迁移新增的强制力：
    # 无权限 member 申请必须 403，否则说明权限点未生效。
    u = await _mk_user(db, "cm_noperm", level="normal", role="member")
    r = await client.post(
        "/api/v1/content/columns/applications",
        headers=_h(u),
        json={"title": "t", "description": "d", "reason": "r"},
    )
    # RequirePermission(columns.application_create) → 403（而非 200/201）
    assert r.status_code == 403


async def test_org_member_cannot_review_application(db: DB, client: Client) -> None:
    # 旧 review 仅 RequireLevel("admin")，org_member(level=admin) 会被放行 200；
    # 迁移后叠加 columns.application_review，org_member 无此权限 → 403。
    # 该用例验证 super_admin 与 org_member 的真实能力差异（此回归由迁移引入）。
    from app.db.models import ColumnApplication

    applicant = await _mk_user(db, "org_rev_app", level="normal", role="member")
    db.add(
        ColumnApplication(user_id=applicant.id, title="t", description="d", reason="r")
    )
    await db.flush()
    # org_member 持有 columns.application_create（可申请）但【不授】application_review。
    await _grant(db, "admin:org_member", "columns.application_create")
    u = await _mk_user(db, "org_rev", level="admin", role="org_member")
    # 越过 2FA 门槛后仍在 handler 内被判 FORBIDDEN → 403
    _set_admin_mfa_cookie(client, u)
    r = await client.post(
        "/api/v1/content/columns/applications/1/review",
        json={"status": "approved"},
    )
    assert r.status_code == 403


async def test_super_admin_can_publish_to_other_column(db: DB, client: Client) -> None:
    # super_admin 持有 columns.publish + column.owner_publish：可代发任意专栏。
    await _grant(
        db,
        "normal:columnist",
        "columns.publish",
    )
    owner = await _mk_user(db, "fowner", level="normal", role="columnist")
    col = Column(slug="c3", title="C3", description="", owner_id=owner.id)
    db.add(col)
    await db.flush()
    await _grant(
        db,
        "admin:super_admin",
        "columns.publish",
        "column.owner_publish",
    )
    sa = await _mk_user(db, "fsa", level="admin", role="super_admin")
    r = await client.post(
        f"/api/v1/content/columns/{col.id}/posts",
        headers=_h(sa, role="super_admin"),
        json={"title": "t", "content": "c", "category": "x"},
    )
    assert r.status_code in (200, 201)
