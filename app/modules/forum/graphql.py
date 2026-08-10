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
"""

import json

import strawberry
from sqlalchemy import func
from sqlalchemy.orm import Session
from strawberry import ID
from strawberry.types.info import Info

from app.db.models import ForumPost, User


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


def _iso_text(p: ForumPost) -> str:
    """created_at 可能是文本或日期对象，统一转字符串。"""
    return p.created_at if isinstance(p.created_at, str) else str(p.created_at)


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


def _load_authors(db: Session, user_ids: list[int]) -> dict[int, Author]:
    """批量加载作者，避免逐条查询的 N+1。"""
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(set(user_ids))).all()
    return {u.id: _to_author(u) for u in users}


def _post_to_graphql(p: ForumPost, author: Author | None) -> Post:
    return Post(
        id=p.id,
        title=p.title,
        excerpt=p.excerpt,
        content=p.content,
        categoryId=p.category_id,
        tags=(json.loads(p.tags) if p.tags else []),
        isPinned=bool(p.is_pinned),
        isFeatured=bool(p.is_featured),
        viewCount=p.view_count,
        likeCount=p.like_count,
        commentCount=p.comment_count,
        bookmarkCount=p.bookmark_count,
        forwardCount=p.forward_count,
        createdAt=_iso_text(p),
        author=author,
    )


def _get_db(info: Info) -> Session:
    """从请求上下文取会话（由 main.py 的 context_getter 经 DI 注入）。"""
    return info.context["db"]


@strawberry.type
class Query:
    @strawberry.field
    def posts(
        self,
        info: Info,
        category_id: ID | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> PostConnection:
        db = _get_db(info)
        cat: str | None = str(category_id) if category_id is not None else None
        total = db.query(func.count(ForumPost.id))
        base = db.query(ForumPost)
        if cat:
            total = total.filter(ForumPost.category_id == cat)
            base = base.filter(ForumPost.category_id == cat)
        total_count = total.scalar() or 0
        posts = (
            base.order_by(ForumPost.is_pinned.desc(), ForumPost.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        authors = _load_authors(db, [p.author_id for p in posts])
        items = [_post_to_graphql(p, authors.get(p.author_id)) for p in posts]
        return PostConnection(items=items, total=total_count)

    @strawberry.field
    def post(self, info: Info, id: ID) -> Post | None:
        db = _get_db(info)
        post_obj = db.query(ForumPost).filter(ForumPost.id == int(id)).first()
        if post_obj is None:
            return None
        authors = _load_authors(db, [post_obj.author_id])
        return _post_to_graphql(post_obj, authors.get(post_obj.author_id))


schema = strawberry.Schema(query=Query)
