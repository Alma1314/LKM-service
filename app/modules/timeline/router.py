"""时间线路由：follow（关注流）/ hot（全站热门）。

匿名：仅 ``hot``（无关注集合）。登录：``follow`` 需关注关系，``hot`` 全站。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_read_session
from app.modules.auth.deps import CurrentUser, get_optional_user
from app.modules.common import ApiResp
from app.modules.timeline.schemas import FeedResponse
from app.modules.timeline.service import get_timeline

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("", response_model=ApiResp[FeedResponse])
@respond
async def get_timeline_endpoint(
    cursor: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    mode: str = Query("follow", pattern="^(follow|hot)$"),
    cur: CurrentUser | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_read_session),
) -> FeedResponse:
    user_id = cur.id if cur is not None else None
    return await get_timeline(
        db, user_id=user_id, mode=mode, cursor=cursor, limit=limit
    )
