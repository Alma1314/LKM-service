"""seed_rbac 幂等写入默认映射。"""
from sqlalchemy import func, select

from app.db.models import RolePermission
from app.modules.rbac.permissions import DEFAULT_GRANTS
from app.modules.rbac.seed import seed_rbac
from tests.conftest import DB


async def test_seed_writes_default_grants(db: DB) -> None:
    inserted = await seed_rbac(db)
    assert inserted == sum(len(v) for v in DEFAULT_GRANTS.values())
    total = (await db.execute(select(func.count()).select_from(RolePermission))).scalar_one()
    assert total == inserted


async def test_seed_idempotent(db: DB) -> None:
    await seed_rbac(db)
    first = (await db.execute(select(func.count()).select_from(RolePermission))).scalar_one()
    await seed_rbac(db)  # 再次执行不重复
    second = (await db.execute(select(func.count()).select_from(RolePermission))).scalar_one()
    assert first == second
