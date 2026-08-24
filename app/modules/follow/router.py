"""关注关系路由：关注/取消关注用户与版块 + 查询（我关注列表、目标状态）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.auth.deps import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from app.modules.common import ApiResp, ListData
from app.modules.follow import service as follow_service
from app.modules.follow.schemas import (
    FollowBoard,
    FollowState,
    FollowToggle,
    FollowUser,
)

user_follow_router = APIRouter(prefix="/users", tags=["follow"])
board_follow_router = APIRouter(prefix="/boards", tags=["follow"])


@user_follow_router.post("/{user_id}/follow", response_model=ApiResp[FollowToggle])
@respond
async def follow_a_user(
    user_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.follow_user(db, cur.id, user_id)
    return FollowToggle(following=True)


@user_follow_router.delete("/{user_id}/follow", response_model=ApiResp[FollowToggle])
@respond
async def unfollow_a_user(
    user_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.unfollow_user(db, cur.id, user_id)
    return FollowToggle(following=False)


@board_follow_router.post("/{board_id}/follow", response_model=ApiResp[FollowToggle])
@respond
async def follow_a_board(
    board_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.follow_board(db, cur.id, board_id)
    return FollowToggle(following=True)


@board_follow_router.delete("/{board_id}/follow", response_model=ApiResp[FollowToggle])
@respond
async def unfollow_a_board(
    board_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.unfollow_board(db, cur.id, board_id)
    return FollowToggle(following=False)


@user_follow_router.get("/me/following", response_model=ApiResp[ListData[FollowUser]])
@respond
async def my_following_users(
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, list[FollowUser]]:
    rows = await follow_service.list_following_users(db, cur.id)
    return {
        "items": [
            FollowUser(user_id=uid, display_name=name, avatar=avatar)
            for uid, name, avatar in rows
        ]
    }


@user_follow_router.get("/{user_id}/follow/status", response_model=ApiResp[FollowState])
@respond
async def user_follow_status(
    user_id: int,
    cur: CurrentUser | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
) -> FollowState:
    if cur is None:
        return FollowState(is_following=False)
    following = await follow_service.is_following_user(db, cur.id, user_id)
    return FollowState(is_following=following)


@board_follow_router.get("/me/following", response_model=ApiResp[ListData[FollowBoard]])
@respond
async def my_following_boards(
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, list[FollowBoard]]:
    rows = await follow_service.list_followed_boards(db, cur.id)
    return {"items": [FollowBoard(board_id=bid, title=title) for bid, title in rows]}
