"""require_owner 底层谓词 check_owner：admin/属主/他人三分支。"""

import pytest

from app.core.err import BizError, CommonErr
from app.db.models import ContentItem, RolePermission
from app.modules.auth.deps import CurrentUser
from app.modules.rbac.permissions import DEFAULT_GRANTS, Permission
from app.modules.rbac.service import check_owner
from tests.conftest import DB


@pytest.fixture(autouse=True)
async def _seed_grants(db: DB) -> None:
    """将默认角色→权限映射落库，否则 role_has_permission 一律为空：
    admin 分支无从验证（admin:super_admin 需 content_owner_delete 授权）。"""
    for role, grants in DEFAULT_GRANTS.items():
        for g in grants:
            db.add(RolePermission(role_name=role, permission=g.permission.value))
    await db.flush()


def _actor(user_id: int) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        account_level="normal",
        role="member",
        email=None,
        phone=None,
    )


def _admin(user_id: int) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        account_level="admin",
        role="super_admin",
        email=None,
        phone=None,
    )


async def _mk_post(db: DB, author_id: int) -> int:
    post = ContentItem(
        content_type="discussion",
        board_id=1,
        author_id=author_id,
        title="t",
        content="c",
    )
    db.add(post)
    await db.flush()
    return int(post.id)


async def test_owner_allowed_by_id(db: DB) -> None:
    pid = await _mk_post(db, 7)
    await check_owner(
        db, _actor(7), pid, ContentItem, "author_id", Permission.content_owner_delete
    )
    # 无异常即通过


async def test_foreign_forbidden(db: DB) -> None:
    pid = await _mk_post(db, 7)
    with pytest.raises(BizError) as exc:
        await check_owner(
            db,
            _actor(99),
            pid,
            ContentItem,
            "author_id",
            Permission.content_owner_delete,
        )
    assert exc.value.errcode == CommonErr.FORBIDDEN


async def test_admin_allowed(db: DB) -> None:
    pid = await _mk_post(db, 7)
    await check_owner(
        db, _admin(1), pid, ContentItem, "author_id", Permission.content_owner_delete
    )


async def test_admin_requires_grant(db: DB) -> None:
    # admin 但如果 role 未被授予该 object 权限点（例如 admin:org_member 无 content_owner_delete）则仍拒
    pid = await _mk_post(db, 7)
    org = CurrentUser(
        id=2, account_level="admin", role="org_member", email=None, phone=None
    )
    with pytest.raises(BizError):
        await check_owner(
            db, org, pid, ContentItem, "author_id", Permission.content_owner_delete
        )
