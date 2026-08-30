"""content RBAC 迁移：发帖权限点、发言准入（认证）、删帖属主校验的 HTTP 级验证。

由 forum 测试迁移（test_boards_forum / test_forum_rbac）承接，URL/权限点/字段对齐
content 端点（/api/v1/content/items）与 content schema（discussion 发帖不带专栏）。

覆盖：
- normal 用户发帖需 content.create 权限点
- local 用户无 content.create → 403
- require_certified 板块未通过通识考试发帖 → CERTIFICATION_REQUIRED
- 删除他人内容项 → 403（check_owner/content.owner_delete）
- 删除自建内容项 → 200
"""

from sqlalchemy import select

from app.core.err import CommonErr
from app.db.models import Board, Exam, ExamCertificate, Profile, RolePermission, User
from app.modules.auth.security import create_access_token
from app.modules.content.errors import BoardErr
from tests.conftest import DB, Client


async def _mk_user(
    db: DB, uname: str, level: str = "normal", role: str = "member"
) -> User:
    user = User(
        username=uname,
        account_level=level,
        hashed_password="content-rbac-test-placeholder-not-a-real-hash",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, role=role, nickname=uname))
    await db.flush()
    return user


async def _mk_board(db: DB, *, owner_id: int | None = None) -> int:
    board = Board(slug="b1", title="B", description="", owner_id=owner_id)
    db.add(board)
    await db.flush()
    return int(board.id)


async def _seed_perm(db: DB, role: str, permission: str) -> None:
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
    tok = create_access_token(
        user_id=user.id, account_level=user.account_level, role=role
    )
    return {"Authorization": f"Bearer {tok}"}


async def test_normal_can_post(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "content.create")
    board = await _mk_board(db)
    user = await _mk_user(db, "nomo", level="normal", role="member")
    r = await client.post(
        "/api/v1/content/items",
        headers=_headers(user),
        json={"board_id": board, "title": "t", "content": "c"},
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert r.json()["data"]["author_id"] == user.id
    assert r.json()["data"]["content_type"] == "discussion"


async def test_local_cannot_post(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "content.create")
    board = await _mk_board(db)
    user = await _mk_user(db, "local_u", level="local", role="member")
    r = await client.post(
        "/api/v1/content/items",
        headers=_headers(user),
        json={"board_id": board, "title": "t", "content": "c"},
    )
    assert r.status_code == 403


async def test_uncertified_blocked_on_certified_board(db: DB, client: Client) -> None:
    """require_certified 板块 + 未通过通识考试用户发帖 → CERTIFICATION_REQUIRED。"""
    await _seed_perm(db, "normal:member", "content.create")
    owner = await _mk_user(db, "owner", role="member")
    board = Board(
        slug="cert",
        title="C",
        description="",
        owner_id=owner.id,
        require_certified=True,
    )
    db.add(board)
    await db.flush()
    novice = await _mk_user(db, "novice", role="member")

    r = await client.post(
        "/api/v1/content/items",
        headers=_headers(novice),
        json={"board_id": int(board.id), "title": "t", "content": "c"},
    )

    assert r.status_code == 403
    assert r.json()["code"] == BoardErr.CERTIFICATION_REQUIRED


async def test_certified_allowed_on_certified_board(db: DB, client: Client) -> None:
    """通过通识考试的用户可在 require_certified 板块发帖。"""
    await _seed_perm(db, "normal:member", "content.create")
    owner = await _mk_user(db, "owner", role="member")
    board = Board(
        slug="cert2",
        title="C2",
        description="",
        owner_id=owner.id,
        require_certified=True,
    )
    db.add(board)
    await db.flush()
    cert_user = await _mk_user(db, "certified", role="member")
    exam = Exam(type="exam", title="初级", unlock_level="normal")
    db.add(exam)
    await db.flush()
    db.add(
        ExamCertificate(
            user_id=cert_user.id, exam_id=exam.id, passed=True, cert_no="CERT-C-1"
        )
    )
    await db.flush()

    r = await client.post(
        "/api/v1/content/items",
        headers=_headers(cert_user),
        json={"board_id": int(board.id), "title": "t", "content": "c"},
    )

    assert r.status_code == 200
    assert r.json()["code"] == 0


async def test_foreign_cannot_delete(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "content.create")
    board = await _mk_board(db)
    a = await _mk_user(db, "fred", role="member")
    b = await _mk_user(db, "alice", role="member")
    rp = await client.post(
        "/api/v1/content/items",
        headers=_headers(a),
        json={"board_id": board, "title": "t", "content": "c"},
    )
    item_id = rp.json()["data"]["id"]
    r = await client.delete(f"/api/v1/content/items/{item_id}", headers=_headers(b))
    assert r.status_code == 403
    assert r.json()["code"] == CommonErr.FORBIDDEN


async def test_owner_can_delete(db: DB, client: Client) -> None:
    await _seed_perm(db, "normal:member", "content.create")
    board = await _mk_board(db)
    a = await _mk_user(db, "owner_u", role="member")
    rp = await client.post(
        "/api/v1/content/items",
        headers=_headers(a),
        json={"board_id": board, "title": "t", "content": "c"},
    )
    item_id = rp.json()["data"]["id"]
    r = await client.delete(f"/api/v1/content/items/{item_id}", headers=_headers(a))
    assert r.status_code == 200
