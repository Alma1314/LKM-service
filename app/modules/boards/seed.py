"""幂等 seed：基础板块。用法 python -m app.modules.boards.seed。"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.auth.models  # noqa: F401
from app.db.models import Board
from app.db.session import new_session

_BASE_BOARDS = [
    {
        "slug": "math",
        "title": "数学",
        "description": "数学讨论与答疑",
        "is_public": True,
    },
    {
        "slug": "physics",
        "title": "物理",
        "description": "物理讨论与答疑",
        "is_public": True,
    },
    {
        "slug": "chemistry",
        "title": "化学",
        "description": "化学讨论与答疑",
        "is_public": True,
    },
    {
        "slug": "biology",
        "title": "生物",
        "description": "生物讨论与答疑",
        "is_public": True,
    },
    {
        "slug": "computer",
        "title": "计算机",
        "description": "编程与计算机科学",
        "is_public": True,
    },
    {
        "slug": "platform",
        "title": "平台讨论",
        "description": "社区规则、意见与帮助",
        "is_public": True,
    },
]


async def seed_boards(db: AsyncSession) -> int:
    created = 0
    for spec in _BASE_BOARDS:
        exists = await db.scalar(select(Board.id).where(Board.slug == spec["slug"]))
        if exists is not None:
            continue
        db.add(Board(**spec))
        await db.flush()
        created += 1
    return created


async def main() -> None:
    db = await new_session()
    try:
        created = await seed_boards(db)
        await db.commit()
        print(f"seeded {created} boards")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
