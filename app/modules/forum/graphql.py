"""论坛模块的 GraphQL schema 与解析器。

前端（urql）按以下契约请求（见 LKM-official-website/src/features/forum/graphql/queries.ts）：

    query PostList($categoryId: ID, $page: Int!, $pageSize: Int!) {
      posts(categoryId: $categoryId, page: $page, pageSize: $pageSize) {
        total
        items { id title excerpt categoryId tags isPinned isFeatured
                viewCount likeCount commentCount createdAt author { id displayName avatar username } }
      }
    }

    query PostDetail($id: ID!) {
      post(id: $id) { id title content excerpt categoryId tags isPinned isFeatured
                      viewCount likeCount commentCount bookmarkCount forwardCount
                      createdAt author { id displayName avatar username bio } }
    }

说明：
- post.id / author.id 在后端为 int，GraphQL ID 直接使用 int，前端同步为 number。
- categoryId 前后端均为字符串（板块 slug）。
- forwardCount / bio 为本次新增的 DB 列。
- 列表/详情查询复用 REST 的 service（forum/service.py），仅在此组装作者对象，
  避免同一套论坛分页/过滤逻辑在 REST 与 GraphQL 各写一份。
"""

from dataclasses import dataclass

import strawberry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from strawberry import ID
from strawberry.fastapi import BaseContext
from strawberry.types.info import Info

from app.db.models import User
from app.modules.forum.service import get_post as service_get_post, list_posts as service_list_posts


@strawberry.type
class Author:
    id: int
    displayName: str | None
    avatar: str | None
    username: str
    bio: str | None


@strawberry.type
class Post:
    id: int
    title: str
    excerpt: str
    content: str
    categoryId: str
    tags: list[str]
    isPinned: bool
    isFeatured: bool
    viewCount: int
    likeCount: int
    commentCount: int
    bookmarkCount: int
    forwardCount: int
    createdAt: str
    author: Author | None


@strawberry.type
class PostConnection:
    items: list[Post]
    total: int


def _display_name(user: User) -> str | None:
    """displayName 取昵称，缺失时回退为 None（前端有兜底）。"""
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return None


def _to_author(user: User) -> Author:
    profile = user.profile
    return Author(
        id=user.id,
        displayName=_display_name(user),
        avatar=profile.avatar if profile else None,
        username=user.username,
        bio=profile.bio if profile else None,
    )


async def _load_authors(db: AsyncSession, user_ids: list[int]) -> dict[int, Author]:
    """批量加载作者，避免逐条查询的 N+1。"""
    if not user_ids:
        return {}
    result = await db.execute(
        select(User).where(User.id.in_(set(user_ids))).options(selectinload(User.profile))
    )
    users = result.scalars().all()
    return {u.id: _to_author(u) for u in users}


@dataclass
class GraphQLContext(BaseContext):
    """GraphQL 请求上下文：持有当前请求的数据库会话。

    会话由 main.py 中 GraphQLRouter 的 context_getter 经 FastAPI 依赖注入
    （Depends(get_session)），与 REST 端点共用同一会话依赖，便于测试 override。
    """

    db: AsyncSession


def _get_db(info: Info) -> AsyncSession:
    """从请求上下文取会话。"""
    return info.context.db


@strawberry.type
class Query:
    @strawberry.field
    async def posts(
        self,
        info: Info,
        category_id: ID | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> PostConnection:
        db = _get_db(info)
        cat: str | None = str(category_id) if category_id is not None else None

        page_data = await service_list_posts(db, page=page, limit=page_size, category_id=cat)

        author_ids = list({p.author_id for p in page_data.items})
        authors = await _load_authors(db, author_ids)

        items = [
            Post(
                id=p.id,
                title=p.title,
                excerpt=p.excerpt,
                content=p.content,
                categoryId=p.category_id,
                tags=p.tags,
                isPinned=p.is_pinned,
                isFeatured=p.is_featured,
                viewCount=p.view_count,
                likeCount=p.like_count,
                commentCount=p.comment_count,
                bookmarkCount=p.bookmark_count,
                forwardCount=p.forward_count,
                createdAt=p.created_at.isoformat(),
                author=authors.get(p.author_id),
            )
            for p in page_data.items
        ]
        return PostConnection(items=items, total=page_data.total)

    @strawberry.field
    async def post(self, info: Info, id: ID) -> Post | None:
        db = _get_db(info)
        try:
            post_info = await service_get_post(db, int(id), bump_view=False)
        except Exception:
            return None

        authors = await _load_authors(db, [post_info.author_id])
        author = authors.get(post_info.author_id)
        return Post(
            id=post_info.id,
            title=post_info.title,
            excerpt=post_info.excerpt,
            content=post_info.content,
            categoryId=post_info.category_id,
            tags=post_info.tags,
            isPinned=post_info.is_pinned,
            isFeatured=post_info.is_featured,
            viewCount=post_info.view_count,
            likeCount=post_info.like_count,
            commentCount=post_info.comment_count,
            bookmarkCount=post_info.bookmark_count,
            forwardCount=post_info.forward_count,
            createdAt=post_info.created_at.isoformat(),
            author=author,
        )


schema = strawberry.Schema(query=Query)
