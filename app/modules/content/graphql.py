"""content（统一内容源）与 boards（板块树）的只读 GraphQL schema 与解析器。

复用 REST 的 service 读函数 + content/service 的批量 map，避免双写分页/过滤逻辑；
GraphQL 字段 camelCase、时间 isoformat、id 用 int。boards 用于论坛分类轴。
"""

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types.info import Info

from app.core.err import BizError
from app.modules.boards.service import list_boards
from app.modules.content.errors import ContentErr
from app.modules.content.schemas import ContentCommentInfo, ContentItemInfo
from app.modules.content.service import (
    get_item,
    get_item_by_slug,
    list_comments,
    list_items,
)

# ---- 节点类型 ----


@strawberry.type
class ContentAuthor:
    id: int
    name: str


@strawberry.type
class GraphContentItem:
    id: int
    contentType: str
    boardId: int
    authorId: int | None
    authorName: str
    publisher: str | None
    department: str | None
    columnId: int | None
    columnTitle: str
    qaQuestionId: int | None
    slug: str | None
    title: str
    excerpt: str
    summary: str | None
    cover: str | None
    keywords: list[str]
    content: str
    tags: list[str]
    status: str
    isPinned: bool
    isFeatured: bool
    viewCount: int
    likeCount: int
    commentCount: int
    bookmarkCount: int
    forwardCount: int
    readingTime: int
    createdAt: str
    publishedAt: str | None


@strawberry.type
class GraphContentComment:
    id: int
    contentId: int
    authorId: int
    authorName: str
    content: str
    floorNumber: int
    parentId: int | None
    likeCount: int
    createdAt: str


@strawberry.type
class GraphContentPage:
    items: list[GraphContentItem]
    total: int
    page: int
    pages: int


@strawberry.type
class GraphCommentPage:
    items: list[GraphContentComment]
    total: int
    page: int
    pages: int


@strawberry.type
class GraphBoard:
    id: int
    slug: str
    title: str
    description: str
    parentId: int | None
    ownerId: int | None
    status: str
    requireCertified: bool
    dailyPostLimit: int
    isPublic: bool
    createdAt: str


def _map_item(item: ContentItemInfo) -> GraphContentItem:
    return GraphContentItem(
        id=item.id,
        contentType=item.content_type,
        boardId=item.board_id,
        authorId=item.author_id,
        authorName=item.author_name,
        publisher=item.publisher,
        department=item.department,
        columnId=item.column_id,
        columnTitle=item.column_title,
        qaQuestionId=item.qa_question_id,
        slug=item.slug,
        title=item.title,
        excerpt=item.excerpt,
        summary=item.summary,
        cover=item.cover,
        keywords=item.keywords,
        content=item.content,
        tags=item.tags,
        status=item.status,
        isPinned=item.is_pinned,
        isFeatured=item.is_featured,
        viewCount=item.view_count,
        likeCount=item.like_count,
        commentCount=item.comment_count,
        bookmarkCount=item.bookmark_count,
        forwardCount=item.forward_count,
        readingTime=item.reading_time,
        createdAt=item.created_at.isoformat(),
        publishedAt=item.published_at.isoformat() if item.published_at else None,
    )


def _map_comment(c: ContentCommentInfo) -> GraphContentComment:
    return GraphContentComment(
        id=c.id,
        contentId=c.content_id,
        authorId=c.author_id,
        authorName=c.author_name,
        content=c.content,
        floorNumber=c.floor_number,
        parentId=c.parent_id,
        likeCount=c.like_count,
        createdAt=c.created_at.isoformat(),
    )


def _get_db(info: Info) -> AsyncSession:
    return info.context.db


@strawberry.type
class ContentQuery:
    @strawberry.field
    async def contentItems(
        self,
        info: Info,
        page: int = 1,
        pageSize: int = 20,
        boardId: int | None = None,
        contentType: str | None = None,
    ) -> GraphContentPage:
        db = _get_db(info)
        page_data = await list_items(
            db, page=page, limit=pageSize, board_id=boardId, content_type=contentType
        )
        return GraphContentPage(
            items=[_map_item(i) for i in page_data.items],
            total=page_data.total,
            page=page_data.page,
            pages=page_data.pages,
        )

    @strawberry.field
    async def contentItem(self, info: Info, id: int) -> GraphContentItem | None:
        db = _get_db(info)
        try:
            item = await get_item(db, id, bump_view=False)
        except BizError as e:
            if e.errcode != ContentErr.CONTENT_NOT_FOUND:
                raise
            return None
        return _map_item(item)

    @strawberry.field
    async def contentItemBySlug(self, info: Info, slug: str) -> GraphContentItem | None:
        db = _get_db(info)
        try:
            item = await get_item_by_slug(db, slug)
        except BizError as e:
            if e.errcode != ContentErr.CONTENT_NOT_FOUND:
                raise
            return None
        return _map_item(item)

    @strawberry.field
    async def contentComments(
        self, info: Info, itemId: int, page: int = 1, pageSize: int = 20
    ) -> GraphCommentPage:
        db = _get_db(info)
        try:
            page_data = await list_comments(db, itemId, page=page, limit=pageSize)
        except BizError as e:
            if e.errcode != ContentErr.CONTENT_NOT_FOUND:
                raise
            return GraphCommentPage(items=[], total=0, page=page, pages=0)
        return GraphCommentPage(
            items=[_map_comment(c) for c in page_data.items],
            total=page_data.total,
            page=page_data.page,
            pages=page_data.pages,
        )

    @strawberry.field
    async def boards(self, info: Info) -> list[GraphBoard]:
        db = _get_db(info)
        board_outs = await list_boards(db)
        return [
            GraphBoard(
                id=b.id,
                slug=b.slug,
                title=b.title,
                description=b.description,
                parentId=b.parent_id,
                ownerId=b.owner_id,
                status=b.status,
                requireCertified=b.require_certified,
                dailyPostLimit=b.daily_post_limit,
                isPublic=b.is_public,
                createdAt=b.created_at.isoformat(),
            )
            for b in board_outs
        ]
