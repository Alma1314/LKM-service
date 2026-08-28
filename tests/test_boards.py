"""boards 模块 service 层测试：CRUD、板块申请/审核、禁言、发言准入。"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.db.models import Board, User
from app.modules.boards.errors import BoardErr
from app.modules.boards.schemas import (
    BanRequest,
    BoardApplicationCreate,
    BoardCreate,
    BoardUpdate,
    ReviewBoardApplicationRequest,
)
from app.modules.boards.service import (
    ban_user,
    check_post_allowed,
    create_board_ex,
    get_board_ex,
    is_banned,
    list_boards,
    review_application,
    submit_application,
    unban_user,
    update_board_ex,
)


async def _user(
    db: AsyncSession, username: str = "alice", level: str = "normal"
) -> int:
    from app.db.models import Profile
    from app.modules.auth.security import hashpwd

    u = User(
        username=username,
        email=f"{username}@e.com",
        hashed_password=await hashpwd("secret123"),
        account_level=level,
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, nickname=username))
    await db.flush()
    return u.id


class TestBoardService:
    async def test_create_board_and_slug_conflict(self, db: AsyncSession):
        owner = await _user(db, "alice")
        b = await create_board_ex(db, BoardCreate(slug="math", title="数学"), owner)
        assert b.slug == "math"
        assert b.owner_id == owner
        with pytest.raises(BizError) as e:
            await create_board_ex(db, BoardCreate(slug="math", title="重复"), owner)
        assert e.value.errcode == BoardErr.SLUG_CONFLICT

    async def test_list_boards(self, db: AsyncSession):
        owner = await _user(db)
        await create_board_ex(db, BoardCreate(slug="math", title="M"), owner)
        boards = await list_boards(db)
        assert len(boards) == 1

    async def test_update_board_owner_only(self, db: AsyncSession):
        owner = await _user(db, "a")
        other = await _user(db, "b")
        b = await create_board_ex(db, BoardCreate(slug="m", title="M"), owner)
        with pytest.raises(BizError) as e:
            await update_board_ex(db, b.id, other, BoardUpdate(title="改"))
        assert e.value.errcode == BoardErr.NOT_BOARD_OWNER
        # owner 能改
        await update_board_ex(db, b.id, owner, BoardUpdate(title="新标题"))
        assert (await get_board_ex(db, b.id)).title == "新标题"

    async def test_application_review_creates_board(self, db: AsyncSession):
        applicant = await _user(db, "app")
        app = await submit_application(
            db,
            applicant,
            BoardApplicationCreate(
                title="板", description="d", reason="r", slug="newb"
            ),
        )
        assert app.status == "pending"
        reviewer = await _user(db, "admin_", level="admin")
        out = await review_application(
            db, app.id, reviewer, ReviewBoardApplicationRequest(approve=True)
        )
        assert out.status == "approved"
        board = await db.scalar(select(Board).where(Board.slug == "newb"))
        assert board is not None
        assert board.owner_id == applicant

    async def test_review_twice_rejected(self, db: AsyncSession):
        applicant = await _user(db)
        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            BoardApplicationCreate(title="t", description="d", reason="r", slug="s1"),
        )
        await review_application(
            db, app.id, reviewer, ReviewBoardApplicationRequest(approve=True)
        )
        with pytest.raises(BizError) as e:
            await review_application(
                db, app.id, reviewer, ReviewBoardApplicationRequest(approve=True)
            )
        assert e.value.errcode == BoardErr.APPLICATION_ALREADY_REVIEWED

    async def test_ban_and_is_banned(self, db: AsyncSession):
        owner = await _user(db, "o")
        target = await _user(db, "t")
        b = await create_board_ex(db, BoardCreate(slug="x", title="X"), owner)
        board = await get_board_ex(db, b.id)
        await ban_user(db, board, owner, BanRequest(user_id=target, hours=24))
        assert await is_banned(db, b.id, target) is True
        await unban_user(db, board, owner, target)
        assert await is_banned(db, b.id, target) is False

    async def test_check_post_allowed_daily_limit(self, db: AsyncSession):
        owner = await _user(db)
        # 先建一张 Board 限 1 条
        b = await create_board_ex(
            db, BoardCreate(slug="lim", title="L", daily_post_limit=1), owner
        )
        user = await _user(db, "u")
        from app.modules.forum.schemas import PostCreate
        from app.modules.forum.service import create_post

        # 第一帖通过
        await check_post_allowed(db, b.id, user)
        await create_post(db, user, PostCreate(title="一", content="x", board_id=b.id))
        # 第二帖触限
        with pytest.raises(BizError) as e:
            await check_post_allowed(db, b.id, user)
        assert e.value.errcode == BoardErr.DAILY_POST_LIMIT_REACHED


class TestBoardHierarchy:
    """板块父/子层级：子板块挂父板块，板块广场可嵌套展示。"""

    async def test_create_child_under_parent(self, db: AsyncSession) -> None:
        owner = await _user(db, "h")
        parent = await create_board_ex(
            db, BoardCreate(slug="basic-science", title="基础学科"), owner
        )
        child = await create_board_ex(
            db,
            BoardCreate(slug="math", title="数学", parent_id=parent.id),
            owner,
        )
        assert child.parent_id == parent.id

        board = await db.get(Board, child.id)
        assert board.parent_id == parent.id
        parent_rel = await db.get(Board, board.parent_id)
        assert parent_rel is not None and parent_rel.slug == "basic-science"

    async def test_board_out_exposes_parent_id(self, db: AsyncSession) -> None:
        owner = await _user(db, "hp")
        parent = await create_board_ex(
            db, BoardCreate(slug="applied-science", title="应用学科"), owner
        )
        child = await create_board_ex(
            db,
            BoardCreate(slug="computer", title="计算机", parent_id=parent.id),
            owner,
        )
        assert child.parent_id == parent.id
        # 父板块 parent_id 为空
        assert parent.parent_id is None
