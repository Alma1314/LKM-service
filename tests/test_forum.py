from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr
from app.db.models import Board, ForumPost, Profile, RolePermission, User
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.forum.errors import ForumErr
from app.modules.forum.schemas import CommentCreate, CommentInfo, PostCreate, PostInfo
from app.modules.forum.service import (
    create_comment,
    create_post,
    delete_post,
    get_post,
    like_post,
    list_comments,
    list_posts,
)


async def _user(
    db: AsyncSession,
    username: str = "alice",
    email: str = "alice@example.com",
    nickname: str | None = None,
) -> int:
    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname=nickname))
    await db.flush()
    return user.id


async def _make_board(db: AsyncSession, slug: str = "math") -> int:
    """按 slug 解析（或创建）一个 Board，返回其 id。幂等：同一 slug 复用已有板块。"""
    board = (
        (await db.execute(select(Board).where(Board.slug == slug))).scalars().first()
    )
    if board is None:
        board = Board(slug=slug, title=slug)
        db.add(board)
        await db.flush()
    return board.id


async def _post(
    db: AsyncSession,
    author_id: int = 1,
    title: str = "如何学习微积分",
    board_slug: str = "math",
    tags: tuple[str, ...] = ("数学", "微积分"),
) -> PostInfo:
    return await create_post(
        db,
        author_id,
        PostCreate(
            title=title,
            content="<p>微积分是理解变化与积累的工具，先从极限开始。</p>",
            board_id=await _make_board(db, board_slug),
            tags=list(tags),
        ),
    )


async def _comment(
    db: AsyncSession,
    post_id: int = 1,
    user_id: int = 1,
    content: str = "写得不错",
    parent_id: int | None = None,
) -> CommentInfo:
    return await create_comment(
        db,
        post_id,
        user_id,
        CommentCreate(content=content, parent_id=parent_id),
    )


class TestForumPosts:
    async def should_create_post_with_nickname_and_excerpt(self, db: AsyncSession):
        user_id = await _user(db, nickname="爱丽丝")

        post = await _post(db, author_id=user_id)

        assert post.id == 1
        assert post.author_id == user_id
        assert post.author_name == "爱丽丝"
        assert post.tags == ["数学", "微积分"]
        assert post.excerpt.startswith("微积分是理解变化")

    async def should_use_username_when_no_nickname(self, db: AsyncSession):
        user_id = await _user(db, username="bob", email="bob@example.com")

        post = await _post(db, author_id=user_id)

        assert post.author_name == "bob"

    async def should_list_posts_paginated(self, db: AsyncSession):
        user_id = await _user(db)
        await _post(db, author_id=user_id, title="帖子一")
        await _post(db, author_id=user_id, title="帖子二")

        page = await list_posts(db, page=1, limit=1)

        assert page.total == 2
        assert page.pages == 2
        assert len(page.items) == 1
        assert page.items[0].title == "帖子二"

    async def should_filter_posts_by_board(self, db: AsyncSession):
        user_id = await _user(db)
        await _post(db, author_id=user_id, board_slug="math")
        physics_bid = await _make_board(db, "physics")
        await _post(db, author_id=user_id, title="物理题", board_slug="physics")

        page = await list_posts(db, board_id=physics_bid)

        assert page.total == 1
        assert page.items[0].board_id == physics_bid

    async def should_get_post_and_bump_view(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)

        first = await get_post(db, post.id, bump_view=True)
        second = await get_post(db, post.id, bump_view=True)

        assert first.view_count == 1
        assert second.view_count == 2

    async def should_reject_nonexistent_post(self, db: AsyncSession):
        with pytest.raises(BizError) as exc:
            await get_post(db, 999)

        assert exc.value.errcode == ForumErr.POST_NOT_FOUND

    async def should_delete_own_post(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)

        await delete_post(db, post.id, user_id)

        try:
            found = await get_post(db, post.id)
        except BizError as exc:
            assert exc.errcode == ForumErr.POST_NOT_FOUND
            return
        raise AssertionError(
            f"expected BizError, got post {found.id} (view={found.view_count})"
        )

    async def should_reject_delete_of_others_post(
        self, client: AsyncClient, db: AsyncSession
    ):
        # RBAC 迁移后，delete_post service 不再内联 owner 判定（上移路由层 check_owner）。
        # 此处从 HTTP 层验证：非作者 delete 他人帖子返回 FORBIDDEN。
        author = await _user(db)
        other = await _user(db, username="mallory", email="mallory@example.com")
        post = await _post(db, author_id=author)
        tok = create_access_token(
            user_id=other, account_level="normal", role="member"
        )
        resp = await client.delete(
            f"/api/v1/forum/posts/{post.id}",
            headers={"Authorization": f"Bearer {tok}"},
        )

        assert resp.status_code == 403

    async def should_like_idempotently(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)

        assert await like_post(db, post.id, user_id) == 1
        # 幂等：同一用户重复点赞不重复计数
        assert await like_post(db, post.id, user_id) == 1


class TestForumComments:
    async def should_create_comment_with_floor(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)

        first = await _comment(db, post_id=post.id, user_id=user_id, content="一楼")
        second = await _comment(db, post_id=post.id, user_id=user_id, content="二楼")

        assert first.floor_number == 1
        assert second.floor_number == 2
        assert (await get_post(db, post.id)).comment_count == 2

    async def should_reject_comment_for_nonexistent_post(self, db: AsyncSession):
        user_id = await _user(db)

        with pytest.raises(BizError) as exc:
            await _comment(db, post_id=999, user_id=user_id)

        assert exc.value.errcode == ForumErr.POST_NOT_FOUND

    async def should_reject_reply_to_comment_of_another_post(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)
        other = await _post(db, author_id=user_id, title="另一个帖子")
        parent = await _comment(db, post_id=post.id, user_id=user_id)

        with pytest.raises(BizError) as exc:
            await _comment(db, post_id=other.id, user_id=user_id, parent_id=parent.id)

        assert exc.value.errcode == ForumErr.COMMENT_NOT_FOUND

    async def should_list_comments_ordered_by_floor(self, db: AsyncSession):
        user_id = await _user(db)
        post = await _post(db, author_id=user_id)
        await _comment(db, post_id=post.id, user_id=user_id, content="一楼")
        await _comment(db, post_id=post.id, user_id=user_id, content="二楼")

        page = await list_comments(db, post.id)

        assert page.total == 2
        assert [c.floor_number for c in page.items] == [1, 2]


class TestForumRoutes:
    async def _setup_user(
        self,
        db: AsyncSession,
        username: str = "tester",
        email: str = "tester@example.com",
    ) -> tuple[int, str]:
        user_id = await _user(db, username=username, email=email)
        # RBAC：normal:member 发帖需显式授予 forum.post_create（生产由 seed_rbac 落 DEFAULT_GRANTS；
        # 测试库 create_all 不自动 seed，故在此按需补授权）。
        existing = (
            (
                await db.execute(
                    select(RolePermission.id).where(
                        RolePermission.role_name == "normal:member",
                        RolePermission.permission == "forum.post_create",
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            db.add(
                RolePermission(
                    role_name="normal:member", permission="forum.post_create"
                )
            )
        # 显式 flush：确保后续 HTTP 请求（RequirePermission 判权限）能看到该授权行，
        # 不依赖 autoflush 时序（与 test_boards_forum 的同类修复保持一致）。
        await db.flush()
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    async def _public_math_board(self, db: AsyncSession) -> int:
        return await _make_board(db, "math")

    async def should_reject_create_post_without_auth(
        self, client: AsyncClient, db: AsyncSession
    ):
        await self._setup_user(db)
        board_id = await self._public_math_board(db)
        resp = await client.post(
            "/api/v1/forum/posts",
            json={
                "title": "标题",
                "content": "正文",
                "board_id": board_id,
                "tags": [],
            },
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN

    async def should_create_post_with_token(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id, token = await self._setup_user(db)
        board_id = await self._public_math_board(db)
        resp = await client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "标题",
                "content": "正文",
                "board_id": board_id,
                "tags": ["数学"],
            },
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["author_id"] == user_id

    async def should_list_posts_publicly(self, client: AsyncClient, db: AsyncSession):
        _, token = await self._setup_user(db)
        board_id = await self._public_math_board(db)
        await client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "公开帖", "content": "正文", "board_id": board_id},
        )

        resp = await client.get("/api/v1/forum/posts")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["title"] == "公开帖"

    async def should_delete_own_post_through_api(
        self, client: AsyncClient, db: AsyncSession
    ):
        _, token = await self._setup_user(db)
        board_id = await self._public_math_board(db)
        created_resp = await client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "待删除", "content": "正文", "board_id": board_id},
        )
        created = created_resp.json()["data"]
        post_id = created["id"]

        resp = await client.delete(
            f"/api/v1/forum/posts/{post_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert (await client.get(f"/api/v1/forum/posts/{post_id}")).json()[
            "code"
        ] == ForumErr.POST_NOT_FOUND


class TestForumGraphQL:
    """论坛 GraphQL 查询契约测试（对齐前端 queries.ts）。"""

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

    async def should_query_posts_with_author(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id = await _user(db, username="alice", nickname="爱丽丝")
        board_id = await _make_board(db, "math")
        post = await _post(
            db, author_id=user_id, title="如何学习微积分", board_slug="math"
        )

        data = await self._run(
            client,
            """
            query PostList($boardId: Int, $page: Int!, $pageSize: Int!) {
              posts(boardId: $boardId, page: $page, pageSize: $pageSize) {
                total
                items {
                  id title excerpt boardId tags isPinned isFeatured
                  viewCount likeCount commentCount createdAt
                  author { id displayName avatar username }
                }
              }
            }
            """,
            {"boardId": board_id, "page": 1, "pageSize": 20},
        )

        conn = data["posts"]
        assert conn["total"] == 1
        item = conn["items"][0]
        assert item["id"] == post.id  # int
        assert item["title"] == "如何学习微积分"
        assert item["boardId"] == board_id
        assert item["author"]["id"] == user_id  # int
        assert item["author"]["displayName"] == "爱丽丝"
        assert item["author"]["username"] == "alice"

    async def should_filter_posts_by_category(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id = await _user(db)
        await _post(db, author_id=user_id, title="数学", board_slug="math")
        await _post(db, author_id=user_id, title="物理", board_slug="physics")
        board_id = await _make_board(db, "math")

        data = await self._run(
            client,
            "query($boardId: Int){ posts(boardId: $boardId, page: 1, pageSize: 20){ total items{ id } } }",
            {"boardId": board_id},
        )

        assert data["posts"]["total"] == 1

    async def should_query_post_detail_with_bio_and_forward_count(
        self, client: AsyncClient, db: AsyncSession
    ):
        user_id = await _user(
            db, username="bob", nickname="鲍勃", email="bob@example.com"
        )
        # 给 Profile 设置 bio
        prof = (
            (await db.execute(select(Profile).where(Profile.user_id == user_id)))
            .scalars()
            .first()
        )
        assert prof is not None
        prof.bio = "热爱物理与数学"
        await db.flush()
        post = await _post(
            db, author_id=user_id, title="物理之美", board_slug="physics"
        )
        post_orm = (
            (await db.execute(select(ForumPost).where(ForumPost.id == post.id)))
            .scalars()
            .first()
        )
        assert post_orm is not None
        post_orm.forward_count = 7
        await db.flush()

        data = await self._run(
            client,
            """
            query PostDetail($id: ID!) {
              post(id: $id) {
                id title content boardId tags isPinned isFeatured
                bookmarkCount forwardCount createdAt
                author { id displayName avatar username bio }
              }
            }
            """,
            {"id": str(post.id)},
        )

        p = data["post"]
        assert p["id"] == post.id
        assert p["forwardCount"] == 7
        assert p["author"]["bio"] == "热爱物理与数学"
        assert p["author"]["displayName"] == "鲍勃"

    async def should_return_null_when_post_missing(
        self, client: AsyncClient, db: AsyncSession
    ):
        data = await self._run(
            client,
            "query($id: ID!){ post(id: $id){ id } }",
            {"id": "999"},
        )
        assert data["post"] is None
