"""
后台只读数据端点：/admin/users（用户列表）、/admin/stats（仪表盘统计）。
"""

import contextlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common import (
    ApiResp,
    ListData,
    PageData,
    PaginateDep,
    PaginateParams,
    paginate_pages,
)
from app.core.err import respond
from app.db.session import get_read_session
from app.modules.auth.deps import CurrentUser
from app.modules.auth.models import User
from app.modules.content.models import ContentItem, ContentType
from app.modules.files.models import LibraryFile
from app.modules.rbac.permissions import Permission

from .deps import require_admin
from .permissions import require_permission
from .schemas import AdminStats, AdminTrendItem, AdminUserListItem

router = APIRouter(prefix="/admin", tags=["admin-data"])


@router.get("/users", response_model=ApiResp[PageData[AdminUserListItem]])
@respond
async def admin_list_users(
    keyword: str | None = None,
    include_pii: bool = False,
    _cur: CurrentUser = require_admin,
    pag: PaginateParams = Depends(PaginateDep()),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[AdminUserListItem]:
    """
    用户管理列表。默认隐藏 email/phone（PII），可按用户名/邮箱筛选。
    include_pii 目前仅由调用方自决；若后续要分级管控，请额外加敏感级依赖。
    """
    await require_permission(db, _cur, Permission.admin_users_manage)
    query = select(User)
    count_q = select(func.count(User.id))

    if keyword:
        # 关键字匹配用户名；邮箱不展示时只用用户名匹配，避免泄露式筛选
        query = query.where(User.username.ilike(f"%{keyword}%"))
        count_q = count_q.where(User.username.ilike(f"%{keyword}%"))

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            query.order_by(User.id.desc()).offset(pag.offset).limit(pag.limit)
        )
    ).scalars()
    # 返回 schema 实例而非 model_dump，使响应体为 PageData 实例（Task 1 依赖
    # isinstance 判定位以自动附带 X-Total 头）。
    items = [
        AdminUserListItem(
            id=int(r.id),
            username=r.username,
            account_level=str(r.account_level),
            is_locked=bool(r.is_locked),
            created_at=r.created_at,
            email=r.email if include_pii else None,
            phone=r.phone if include_pii else None,
        )
        for r in rows
    ]

    return PageData(
        items=items,
        total=total,
        page=pag.page,
        pages=paginate_pages(total, pag.limit),
    )


async def _safe_count(db: AsyncSession, stmt: Any) -> int:
    """单计数器容错：某模块表缺失/不可用时不拖垮整页统计（对聚合类后台端点友好）。"""
    try:
        return (await db.execute(stmt)).scalar() or 0
    except Exception:
        return 0


@router.get("/stats", response_model=ApiResp[AdminStats])
@respond
async def admin_stats(
    _cur: CurrentUser = require_admin,
    db: AsyncSession = Depends(get_read_session),
) -> AdminStats:
    """仪表盘聚合统计：注册用户数 / 帖子数 / 文件数 / 待审核文件数。"""
    await require_permission(db, _cur, Permission.admin_dashboard)
    user_count = await _safe_count(db, select(func.count(User.id)))
    post_count = await _safe_count(
        db,
        select(func.count(ContentItem.id)).where(
            ContentItem.content_type == ContentType.DISCUSSION
        ),
    )
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


@router.get("/stats/trend", response_model=ApiResp[ListData[AdminTrendItem]])
@respond
async def admin_trend(
    days: int = Query(14, ge=1, le=90),
    _cur: CurrentUser = require_admin,
    db: AsyncSession = Depends(get_read_session),
) -> ListData[AdminTrendItem]:
    """后台趋势：最近 days 天每日新增注册用户数 + 新增帖子数（日期连续、缺日补 0）。"""

    await require_permission(db, _cur, Permission.admin_dashboard)

    async def _deltas(col: Any, extra_where: Any | None = None) -> dict[date, int]:
        """按某时间列分组统计每日增量；单表异常返回空 dict（_safe_count 同款容错）。
        extra_where 可选附加过滤（如 content_type == discussion）。
        func.date 在 SQLite 返回 'YYYY-MM-DD' 字符串，统一转 date 作 key。"""
        out: dict[date, int] = {}
        try:
            stmt = select(func.date(col).label("d"), func.count()).where(col >= start)
            if extra_where is not None:
                stmt = stmt.where(extra_where)
            rows = (await db.execute(stmt.group_by("d"))).all()
        except Exception:
            return out
        for r in rows:
            raw = r[0]
            if raw is None:
                continue
            r0: str = raw if isinstance(raw, str) else str(raw)
            with contextlib.suppress(ValueError):
                out[date.fromisoformat(r0[:10])] = int(r[1] or 0)
        return out

    # 数据按 UTC 存储/分桶（func.date 解释 naive UTC 值），基准须用 UTC 的"今天"，
    # 否则本地时区偏移（东8区凌晨）会让 start 与分桶错位一天。
    start = datetime.now(UTC).date() - timedelta(days=days - 1)
    user_d = await _deltas(User.created_at)
    # 帖子统计改走统一写源 content_items（content_type == discussion ⇔ 原 forum_posts）
    post_d = await _deltas(
        ContentItem.created_at,
        extra_where=ContentItem.content_type == ContentType.DISCUSSION,
    )

    items: list[AdminTrendItem] = []
    for i in range(days):
        d = start + timedelta(days=i)
        items.append(
            AdminTrendItem(
                date=d,
                user_delta=int(user_d.get(d, 0)),
                post_delta=int(post_d.get(d, 0)),
            )
        )
    return ListData(items=items)
