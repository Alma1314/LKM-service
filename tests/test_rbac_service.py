"""user_has_permission：按复合角色在 role_permissions 表查权限。"""

from app.db.models import RolePermission
from app.modules.rbac.permissions import Permission
from app.modules.rbac.service import role_has_permission
from tests.conftest import DB


async def seed_permission(db: DB, role: str, perm: str) -> None:
    db.add(RolePermission(role_name=role, permission=perm))
    await db.flush()


async def test_role_has_granted(db: DB) -> None:
    await seed_permission(db, "normal:member", "content.create")
    assert await role_has_permission(db, "normal:member", Permission.content_create)
    assert not await role_has_permission(
        db, "normal:member", Permission.articles_review
    )


async def test_role_missing_row(db: DB) -> None:
    assert not await role_has_permission(db, "normal:member", Permission.files_review)
