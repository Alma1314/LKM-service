from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_read_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ModuleStatus, PageData
from app.modules.points.errors import PointsErr  # noqa: F401  (副作用注册由 main 统一)
from app.modules.points.schemas import BalanceOut, LeaderboardEntry, LedgerEntry
from app.modules.points.service import get_balance, leaderboard, list_ledger


def _status() -> ModuleStatus:
    return ModuleStatus(
        module="points",
        status="implemented",
        responsibility="积分核心引擎：balance+ledger 账本，reward/spend/transfer 原子原语，排行榜。",
        next_steps=[
            "QA 悬赏转账回接（阶段5）",
            "竞赛积分回接（reward 接口）",
            "事件自动挂接规则（发帖/评论/加精加分）",
        ],
    )


router = APIRouter(prefix="/points", tags=["points"])


@router.get("/status", response_model=ModuleStatus)
async def points_status() -> ModuleStatus:
    return _status()


@router.get("/me", response_model=ApiResp[BalanceOut])
@respond
async def my_balance(
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_session),
) -> BalanceOut:
    return BalanceOut(user_id=cur.id, balance=await get_balance(db, cur.id))


@router.get("/me/ledger", response_model=ApiResp[PageData[LedgerEntry]])
@respond
async def my_ledger(
    cur: CurrentUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[LedgerEntry]:
    return await list_ledger(db, cur.id, page=page, limit=limit)


@router.get("/leaderboard", response_model=ApiResp[list[LeaderboardEntry]])
@respond
async def points_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_read_session),
) -> list[LeaderboardEntry]:
    return await leaderboard(db, limit=limit)
