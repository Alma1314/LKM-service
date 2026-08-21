"""forum B2a 迁移 + boards 发言准入 + GraphQL 契约集成测试。

覆盖：
- forum 按 board_id 建帖（B2a 迁移后接口契约）
- list 按 board_id 过滤
- 未通过初级通识考试（board.require_certified）拒发言 → CERTIFICATION_REQUIRED
- 禁言拒发言 → BOARD_BANNED
- local 用户在非公开板块拒发言 → BOARD_NOT_PUBLIC
- GraphQL boardId 契约
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.db.models import Board, Profile, User
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.boards.errors import BoardErr
from app.modules.boards.schemas import BanRequest, BoardCreate
from app.modules.boards.service import ban_user, check_post_allowed, create_board_ex
from app.modules.forum.schemas import PostCreate
from app.modules.forum.service import create_post


async def _user(
    db: AsyncSession,
    username: str = "alice",
    email: str | None = None,
    level: str = "normal",
) -> int:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        hashed_password=await hashpwd("secret123456"),
        account_level=level,
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname=username))
    await db.flush()
    return user.id


async def _make_board(
    db: AsyncSession,
    slug: str,
    owner_id: int | None = None,
    *,
    require_certified: bool = False,
    is_public: bool = True,
) -> int:
    return (
        await create_board_ex(
            db,
            BoardCreate(
                slug=slug,
                title=slug,
                require_certified=require_certified,
                is_public=is_public,
            ),
            owner_id,
        )
    ).id


class TestBoardForumPosting:
    """REST 建帖按 board_id：迁移后 B2a 契约。"""

    async def _setup(
        self, db: AsyncSession, username: str = "poster"
    ) -> tuple[int, str]:
        uid = await _user(db, username=username)
        token = create_access_token(user_id=uid, account_level="normal", role="member")
        return uid, token

    async def should_create_post_with_board_id(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id, token = await self._setup(db)
        board_id = await _make_board(db, "math", owner_id=user_id)

        resp = await client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "帖子", "content": "正文", "board_id": board_id},
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["board_id"] == board_id
        assert resp.json()["data"]["author_id"] == user_id

    async def should_list_posts_filtered_by_board(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id, token = await self._setup(db)
        math_bid = await _make_board(db, "math", owner_id=user_id)
        phys_bid = await _make_board(db, "physics", owner_id=user_id)
        for bid in (math_bid, phys_bid):
            await client.post(
                "/api/v1/forum/posts",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": f"帖-{bid}", "content": "x", "board_id": bid},
            )

        resp = await client.get(f"/api/v1/forum/posts?board_id={math_bid}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["board_id"] == math_bid

    async def should_reject_post_for_missing_board(
        self, client: AsyncClient, db: AsyncSession
    ):
        _, token = await self._setup(db)

        resp = await client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "帖", "content": "x", "board_id": 999},
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == BoardErr.BOARD_NOT_FOUND


class TestBoardPostingGate:
    """发言准入：认证 / 禁言 / 可见性 / 日限发（service 层断言 errcode）。"""

    async def should_block_uncertified_user(self, db: AsyncSession):
        owner = await _user(db, "owner")
        board_id = await _make_board(db, "cert", owner_id=owner, require_certified=True)
        # 未绑定任何通过 ExamCertificate，应被挡下
        user = await _user(db, "novice")

        with pytest.raises(BizError) as e:
            await create_post(
                db, user, PostCreate(title="t", content="x", board_id=board_id)
            )
        assert e.value.errcode == BoardErr.CERTIFICATION_REQUIRED

    async def should_allow_certified_user(self, db: AsyncSession):
        owner = await _user(db, "owner")
        board_id = await _make_board(
            db, "cert2", owner_id=owner, require_certified=True
        )
        user = await _user(db, "certified")
        # 通过初级通识考试（type=exam, unlock_level=normal）→ 允许
        from app.db.models import Exam, ExamCertificate

        exam = Exam(type="exam", title="初级", unlock_level="normal")
        db.add(exam)
        await db.flush()
        db.add(
            ExamCertificate(
                user_id=user, exam_id=exam.id, passed=True, cert_no="CERT-TEST-1"
            )
        )
        await db.flush()

        post = await create_post(
            db, user, PostCreate(title="t", content="x", board_id=board_id)
        )
        assert post.board_id == board_id

    async def should_block_banned_user(self, db: AsyncSession):
        owner = await _user(db, "owner")
        board_id = await _make_board(db, "ban", owner_id=owner)
        board = (
            (await db.execute(select(Board).where(Board.id == board_id)))
            .scalars()
            .first()
        )
        assert board is not None
        user = await _user(db, "muted")
        await ban_user(db, board, owner, BanRequest(user_id=user, hours=24))

        with pytest.raises(BizError) as e:
            await create_post(
                db, user, PostCreate(title="t", content="x", board_id=board_id)
            )
        assert e.value.errcode == BoardErr.BOARD_BANNED

    async def should_block_local_user_on_non_public_board(self, db: AsyncSession):
        owner = await _user(db, "owner")
        board_id = await _make_board(db, "private", owner_id=owner, is_public=False)
        # local 用户：account_level 非 normal/admin → 私有板块拒
        local_user = await _user(db, "visitor", level="local")

        with pytest.raises(BizError) as e:
            await check_post_allowed(db, board_id, local_user)
        assert e.value.errcode == BoardErr.BOARD_NOT_PUBLIC
        # normal 用户可通过准入（该板块未禁言、未要求认证、无日限）
        normal_user = await _user(db, "member")
        await check_post_allowed(db, board_id, normal_user)  # 不抛异常

    async def should_block_daily_limit_through_check(self, db: AsyncSession):
        owner = await _user(db, "owner")
        board_id = (
            await create_board_ex(
                db, BoardCreate(slug="lim2", title="L", daily_post_limit=1), owner
            )
        ).id
        user = await _user(db, "u")
        await check_post_allowed(db, board_id, user)
        await create_post(
            db, user, PostCreate(title="一", content="x", board_id=board_id)
        )

        with pytest.raises(BizError) as e:
            await check_post_allowed(db, board_id, user)
        assert e.value.errcode == BoardErr.DAILY_POST_LIMIT_REACHED


class TestBoardForumGraphQL:
    """GraphQL boardId 契约（对齐前端 queries.ts）。"""

    async def _run(
        self, client: AsyncClient, query: str, variables: dict[str, Any]
    ) -> Any:
        resp = await client.post(
            "/graphql", json={"query": query, "variables": variables}
        )
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        assert "errors" not in body, body.get("errors")
        return body["data"]

    async def should_query_posts_by_board(self, client: AsyncClient, db: AsyncSession):
        user_id = await _user(db, username="grapher")
        owner = await _user(db, "owner")
        board_id = await _make_board(db, "math", owner_id=owner)
        await create_post(
            db, user_id, PostCreate(title="帖子A", content="x", board_id=board_id)
        )

        data = await self._run(
            client,
            """
            query PostList($boardId: Int!, $page: Int!, $pageSize: Int!) {
              posts(boardId: $boardId, page: $page, pageSize: $pageSize) {
                total
                items { id title boardId }
              }
            }
            """,
            {"boardId": board_id, "page": 1, "pageSize": 20},
        )

        conn = data["posts"]
        assert conn["total"] == 1
        assert conn["items"][0]["boardId"] == board_id
        assert conn["items"][0]["title"] == "帖子A"
