"""forum 迁移 RBAC：发帖需权限点，删帖需属主的 HTTP 级验证。"""

from sqlalchemy import select

from app.db.models import Board, Profile, RolePermission, User
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


async def _mk_user(db: DB, uname: str, level: str = "normal", role: str = "member") -> User:
    # 注意：users.hashed_password 为 NOT NULL，传占位值以通过约束
    # （brief 的 _mk_user 省略了该字段，会导致 IntegrityError，此处补上）。
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


async def _mk_board(db: DB) -> Board:
    board = Board(slug="b1", title="B", description="", owner_id=None)
    db.add(board)
    await db.flush()
    return board


async def _seed_perm(db: DB, role: str, permission: str) -> None:
    # 幂等：conftest 已按 DEFAULT_GRANTS 预种子默认权限（如 normal:member→forum.post_create），
    # 此处若重复插入会撞 role_permissions 唯一约束，故先判存在再插。
    exists = await db.scalar(
        select(RolePermission.id).where(
            RolePermission.role_name == role,
            RolePermission.permission == permission,
        )
    )
    if exists is None:
        db.add(RolePermission(role_name=role, permission=permission))
        await db.flush()


def _headers(user: User, role: str = "member") -> dict[str, str]:
    # create_access_token 的 role 是必填参数（见 security.py:61）。CurrentUser.role 实际来自 DB
    # profile.role，此处 token 里传的 role 仅须与 _mk_user 写入的 Profile.role 一致即可。
    tok = create_access_token(
        user_id=user.id, account_level=user.account_level, role=role
    )
    return {"Authorization": f"Bearer {tok}"}


async def test_local_cannot_post(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "forum.post_create")
    board = await _mk_board(db)
    user = await _mk_user(db, "local_u", level="local", role="member")
    r = await client.post("/api/v1/forum/posts", headers=_headers(user), json={
        "board_id": board.id, "title": "t", "content": "c"
    })
    assert r.status_code == 403


async def test_normal_can_post(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "forum.post_create")
    board = await _mk_board(db)
    user = await _mk_user(db, "nomo", level="normal", role="member")
    r = await client.post("/api/v1/forum/posts", headers=_headers(user), json={
        "board_id": board.id, "title": "t", "content": "c"
    })
    assert r.status_code == 200


async def test_foreign_cannot_delete(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "forum.post_create")
    board = await _mk_board(db)
    a = await _mk_user(db, "fred", level="normal", role="member")
    b = await _mk_user(db, "alice", level="normal", role="member")
    rp = await client.post("/api/v1/forum/posts", headers=_headers(a), json={
        "board_id": board.id, "title": "t", "content": "c"
    })
    post_id = rp.json()["data"]["id"]
    r = await client.delete(f"/api/v1/forum/posts/{post_id}", headers=_headers(b))
    assert r.status_code == 403


async def test_owner_can_delete(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "forum.post_create")
    await _seed_perm(db, "normal:member", "forum.owner_delete")
    board = await _mk_board(db)
    a = await _mk_user(db, "owner_u", level="normal", role="member")
    rp = await client.post("/api/v1/forum/posts", headers=_headers(a), json={
        "board_id": board.id, "title": "t", "content": "c"
    })
    post_id = rp.json()["data"]["id"]
    r = await client.delete(f"/api/v1/forum/posts/{post_id}", headers=_headers(a))
    assert r.status_code == 200
