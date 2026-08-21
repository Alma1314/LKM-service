"""columns × boards 关联：Column 携带 board_id，seed_columns 正确映射/兜底。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board, Column
from app.modules.boards.schemas import BoardCreate
from app.modules.boards.service import create_board_ex
from app.modules.columns.schemas import ColumnInfo
from app.modules.columns.service import get_column


async def _board(db: AsyncSession, slug: str, title: str = "") -> int:
    return (
        await create_board_ex(db, BoardCreate(slug=slug, title=title or slug), None)
    ).id


class TestColumnBoardRelation:
    async def should_attach_board_id_to_column(self, db: AsyncSession):
        board_id = await _board(db, "math", "数学")
        # 关联所属用户（满足 owner 非空 FK）
        from app.db.models import Profile, User
        from app.modules.auth.security import hashpwd

        u = User(
            username="cowner",
            email="cowner@e.com",
            hashed_password=await hashpwd("secret123"),
            account_level="normal",
        )
        db.add(u)
        await db.flush()
        db.add(Profile(user_id=u.id))
        await db.flush()

        col = Column(
            owner_id=u.id,
            slug="math-notes",
            title="数学笔记",
            description="记录数学学习心得。",
            board_id=board_id,
        )
        db.add(col)
        await db.flush()

        found: ColumnInfo = await get_column(db, col.id)

        assert found.slug == "math-notes"
        assert found.board_id == board_id

    async def should_map_board_id_where_board_exists(self, db: AsyncSession):
        # 只 seed physics 板块；computer 板块缺失，用于验证 board 缺失时兜底为 None
        await _board(db, "physics", "物理")

        from app.modules.columns.seed import seed_columns

        seeded = await seed_columns(db)

        assert seeded > 0
        cosmic = await db.scalar(select(Column).where(Column.slug == "cosmic-notes"))
        algorithm = await db.scalar(
            select(Column).where(Column.slug == "algorithm-beauty")
        )
        assert cosmic is not None
        assert algorithm is not None
        # physics 板块存在：正确映射
        phys_board = await db.scalar(select(Board).where(Board.slug == "physics"))
        assert phys_board is not None
        assert cosmic.board_id == phys_board.id
        # computer 板块缺失：兜底为 None 且不报错
        assert algorithm.board_id is None
        # 无板块关联的专栏（edu-lab / academic-writing）保持 None
        edu = await db.scalar(select(Column).where(Column.slug == "edu-lab"))
        assert edu is not None
        assert edu.board_id is None
