"""关注关系路由：关注/取消关注用户与版块。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp
from app.modules.follow import service as follow_service
from app.modules.follow.schemas import FollowToggle

user_follow_router = APIRouter(prefix="/users", tags=["follow"])
board_follow_router = APIRouter(prefix="/boards", tags=["follow"])


@user_follow_router.post(
    "/{user_id}/follow", response_model=ApiResp[FollowToggle]
)
@respond
async def follow_a_user(
    user_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.follow_user(db, cur.id, user_id)
    return FollowToggle(following=True)


@user_follow_router.delete(
    "/{user_id}/follow", response_model=ApiResp[FollowToggle]
)
@respond
async def unfollow_a_user(
    user_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.unfollow_user(db, cur.id, user_id)
    return FollowToggle(following=False)


@board_follow_router.post(
    "/{board_id}/follow", response_model=ApiResp[FollowToggle]
)
@respond
async def follow_a_board(
    board_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.follow_board(db, cur.id, board_id)
    return FollowToggle(following=True)


@board_follow_router.delete(
    "/{board_id}/follow", response_model=ApiResp[FollowToggle]
)
@respond
async def unfollow_a_board(
    board_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FollowToggle:
    await follow_service.unfollow_board(db, cur.id, board_id)
    return FollowToggle(following=False)
