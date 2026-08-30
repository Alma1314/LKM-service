"""时间线只读 GraphQL：复用 REST 的 get_timeline 读函数，按当前用户（可选）个性化。

字段 camelCase、时间 isoformat。关注流（mode=follow）需用户已登录；匿名按 hot。
"""

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types.info import Info

from app.modules.timeline.service import get_timeline


@strawberry.type
class GraphFeedItem:
    itemType: str
    id: int
    authorId: int | None
    authorName: str
    title: str
    contentPreview: str
    createdAt: str
    boardId: int | None = None
    url: str


@strawberry.type
class GraphFeedResponse:
    items: list[GraphFeedItem]
    nextCursor: str | None


def _get_db(info: Info) -> AsyncSession:
    return info.context.db


def _get_user_id(info: Info) -> int | None:
    return info.context.user_id


@strawberry.type
class TimelineQuery:
    @strawberry.field
    async def timeline(
        self,
        info: Info,
        mode: str = "follow",
        cursor: str | None = None,
        limit: int = 20,
    ) -> GraphFeedResponse:
        db = _get_db(info)
        user_id = _get_user_id(info)
        feed = await get_timeline(
            db, user_id=user_id, mode=mode, cursor=cursor, limit=limit
        )
        return GraphFeedResponse(
            items=[
                GraphFeedItem(
                    itemType=it.item_type,
                    id=it.id,
                    authorId=it.author_id,
                    authorName=it.author_name,
                    title=it.title,
                    contentPreview=it.content_preview,
                    createdAt=it.created_at.isoformat(),
                    boardId=it.board_id,
                    url=it.url,
                )
                for it in feed.items
            ],
            nextCursor=feed.next_cursor,
        )
