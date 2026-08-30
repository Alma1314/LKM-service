"""关注关系只读 GraphQL：复用 follow service 读函数。

按 GraphQLContext.user_id（登录态）返回「我关注」的用户/版块列表；未登录返回空。
"""

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types.info import Info

from app.modules.follow import service as follow_service


@strawberry.type
class GraphFollowUser:
    userId: int
    displayName: str
    avatar: str | None


@strawberry.type
class GraphFollowBoard:
    boardId: int
    title: str


def _get_db(info: Info) -> AsyncSession:
    return info.context.db


def _get_user_id(info: Info) -> int | None:
    return info.context.user_id


@strawberry.type
class FollowQuery:
    @strawberry.field
    async def myFollowingUsers(self, info: Info) -> list[GraphFollowUser]:
        user_id = _get_user_id(info)
        db = _get_db(info)
        if user_id is None:
            return []
        rows = await follow_service.list_following_users(db, user_id)
        return [
            GraphFollowUser(userId=uid, displayName=name, avatar=avatar)
            for uid, name, avatar in rows
        ]

    @strawberry.field
    async def myFollowingBoards(self, info: Info) -> list[GraphFollowBoard]:
        user_id = _get_user_id(info)
        db = _get_db(info)
        if user_id is None:
            return []
        rows = await follow_service.list_followed_boards(db, user_id)
        return [GraphFollowBoard(boardId=bid, title=title) for bid, title in rows]
