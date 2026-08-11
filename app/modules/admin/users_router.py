"""后台只读数据端点：/admin/users（用户列表）、/admin/stats（仪表盘统计）。

权限：require_admin（单一事实源在后端）。端点返回 ApiResp 信封。
PII 默认隐藏：email/phone 仅在 include_pii=True 时返回（后续可接敏感级依赖做更细管控）。
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.models import ForumPost, LibraryFile, User
from app.db.session import get_session
from app.modules.common import ApiResp, ListData

from .deps import require_admin
from .schemas import AdminStats, AdminUserListItem

router = APIRouter(prefix="/admin", tags=["admin-data"])


@router.get("/users", response_model=ApiResp[ListData[AdminUserListItem]])
@respond
async def admin_list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    include_pii: bool = False,
    _cur=require_admin,
    db: AsyncSession = Depends(get_session),
):
    """用户管理列表。默认隐藏 email/phone（PII），可按用户名/邮箱筛选。

    include_pii 目前仅由调用方自决；若后续要分级管控，请额外加敏感级依赖。
    """
    query = select(User)
    count_q = select(func.count(User.id))

    if keyword:
        # 关键字匹配用户名；邮箱不展示时只用用户名匹配，避免泄露式筛选
        query = query.where(User.username.ilike(f"%{keyword}%"))
        count_q = count_q.where(User.username.ilike(f"%{keyword}%"))

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(query.order_by(User.id.desc()).offset((page - 1) * size).limit(size))
    ).scalars()
    items = []
    for r in rows:
        item = AdminUserListItem(
            id=int(r.id),
            username=r.username,
            account_level=str(r.account_level),
            is_locked=bool(r.is_locked),
            created_at=r.created_at,
            email=r.email if include_pii else None,
            phone=r.phone if include_pii else None,
        )
        items.append(item.model_dump())

    return {"items": items, "total": total}


async def _safe_count(db: AsyncSession, stmt: Any) -> int:
    """单计数器容错：某模块表缺失/不可用时不拖垮整页统计（对聚合类后台端点友好）。"""
    try:
        return (await db.execute(stmt)).scalar() or 0
    except Exception:
        return 0


@router.get("/stats", response_model=ApiResp[AdminStats])
@respond
async def admin_stats(
    _cur=require_admin,
    db: AsyncSession = Depends(get_session),
):
    """仪表盘聚合统计：注册用户数 / 帖子数 / 文件数 / 待审核文件数。"""
    user_count = await _safe_count(db, select(func.count(User.id)))
    post_count = await _safe_count(db, select(func.count(ForumPost.id)))
    file_count = await _safe_count(db, select(func.count(LibraryFile.id)))
    file_pending = await _safe_count(
        db,
        select(func.count(LibraryFile.id)).where(LibraryFile.status == "pending"),
    )
    return AdminStats(
        user_count=user_count,
        post_count=post_count,
        file_count=file_count,
        file_pending_count=file_pending,
    )
