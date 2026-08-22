"""boards 迁移 RBAC：申请/审核/负责人/全局管理 权限点接线测试。

审核端点（review_app）走 Admin2FADep（危险操作 2FA，读 cookie），故审核用例需
以 create_admin_access_token(mfa_verified=True) 写入 client cookie 才能越过 2FA 门槛，
从而真正触达 handler 内的 boards_review_application 权限点判定（否则会在 2FA 门槛 401 停下）。
"""
from sqlalchemy import select

from app.db.models import BoardApplication, Profile, RolePermission, User
from app.modules.admin.deps import COOKIE_NAME, COOKIE_PATH, create_admin_access_token
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


async def _mk_user(db: DB, uname: str, level: str = "normal", role: str = "member") -> User:
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
    # profile.role，token 里 role 仅占位（解析时会以 DB profile.role 覆盖）。
    tok = create_access_token(
        user_id=user.id, account_level=user.account_level, role=role
    )
    return {"Authorization": f"Bearer {tok}"}


def _set_admin_mfa_cookie(client: Client, user: User) -> None:
    # 审核端点 Admin2FADep 从 cookie 读后台 access token 且须 mfa_verified 信任。
    tok = create_admin_access_token(user, mfa_verified=True)
    client.cookies.set(COOKIE_NAME, tok, path=COOKIE_PATH)


async def test_member_can_apply(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "boards.create_application")
    u = await _mk_user(db, "bm", level="normal", role="member")
    r = await client.post("/api/v1/boards/applications", headers=_headers(u), json={
        "title": "t", "description": "d", "reason": "r", "slug": "b1"
    })
    assert r.status_code in (200, 201)


async def test_org_cannot_review_application(db: DB, client: Client) -> None:
    # org_member 未授予 boards_review_application → 403（先越 2FA 门槛再判权限）
    await _seed_perm(db, "admin:org_member", "boards.create_application")
    u = await _mk_user(db, "org0", level="admin", role="org_member")
    # 先建一个待审申请（直插 DB）
    db.add(BoardApplication(
        applicant_id=1, title="t", description="d", reason="r", slug="z1", status="pending"
    ))
    await db.flush()
    _set_admin_mfa_cookie(client, u)
    r = await client.post("/api/v1/boards/applications/1/review",
                          json={"approve": True})
    assert r.status_code == 403


async def test_super_admin_can_review_application(db: DB, client: Client) -> None:
    # super_admin 授予 boards_review_application → 审核通过 200
    await _seed_perm(db, "admin:super_admin", "boards.review_application")
    u = await _mk_user(db, "sadmin", level="admin", role="super_admin")
    db.add(BoardApplication(
        applicant_id=1, title="t", description="d", reason="r", slug="z2", status="pending"
    ))
    await db.flush()
    _set_admin_mfa_cookie(client, u)
    r = await client.post("/api/v1/boards/applications/1/review",
                          json={"approve": True})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"


async def test_owner_can_update_board(db: DB, client: Client) -> None:
    from app.db.models import Board
    from app.modules.boards.schemas import BoardCreate
    from app.modules.boards.service import create_board_ex

    owner = await _mk_user(db, "ow1")
    await create_board_ex(db, BoardCreate(slug="ob1", title="原题"), owner.id)
    board_id = (await db.scalar(
        select(Board.id).where(Board.slug == "ob1")
    ))
    r = await client.patch(
        f"/api/v1/boards/{board_id}",
        headers=_headers(owner),
        json={"title": "新题"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "新题"


async def test_non_owner_update_forbidden(db: DB, client: Client) -> None:
    from app.db.models import Board
    from app.modules.boards.schemas import BoardCreate
    from app.modules.boards.service import create_board_ex

    owner = await _mk_user(db, "ow2")
    loser = await _mk_user(db, "loser")
    await create_board_ex(db, BoardCreate(slug="ob2", title="别动"), owner.id)
    # non-owner 普通用户（level=normal, role=member，无 board_owner_manage）→ 403
    r = await client.patch(
        f"/api/v1/boards/{await db.scalar(select(Board.id).where(Board.slug == 'ob2'))}",
        headers=_headers(loser),
        json={"title": "篡改"},
    )
    assert r.status_code == 403
