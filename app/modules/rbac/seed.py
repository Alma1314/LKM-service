"""幂等 seed：按 DEFAULT_GRANTS 写入复合角色→权限点默认映射。

用法::

    python -m app.modules.rbac.seed
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.auth.models  # noqa: F401  （确保 User/Profile 等模型可见）
from app.db.models import (  # noqa: F401  （随 auth.models 一起确保模型元数据可见）
    Base,
    RolePermission,
)
from app.db.session import new_session
from app.modules.rbac.permissions import DEFAULT_GRANTS


async def seed_rbac(db: AsyncSession) -> int:
    """写入各复合角色默认权限；已存在则跳过（幂等）。返回新增行数。"""
    rows: list[RolePermission] = []
    for role_name, grants in DEFAULT_GRANTS.items():
        for grant in grants:
            exists = await db.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_name == role_name,
                    RolePermission.permission == grant.permission.value,
                )
            )
            if exists is None:
                rows.append(
                    RolePermission(
                        role_name=role_name,
                        permission=grant.permission.value,
                    )
                )
    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)


async def _main() -> None:
    db = await new_session()  # new_session() 返回单个 AsyncSession（非 factory），与 boards/seed.py 一致
    try:
        n = await seed_rbac(db)
        await db.commit()
        print(f"seed_rbac: inserted {n} role-permission rows")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
