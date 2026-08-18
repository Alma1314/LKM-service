"""后台举报端点：/admin/reports（举报列表）。

后台只读端点，须持有有效后台 cookie 会话（require_admin）。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.models import Report
from app.db.session import get_read_session
from app.modules.auth.deps import CurrentUser
from app.modules.common import ApiResp, ListData

from .deps import require_admin
from .schemas import AdminReportListItem

router = APIRouter(prefix="/admin", tags=["admin-data"])


@router.get("/reports", response_model=ApiResp[ListData[AdminReportListItem]])
@respond
async def admin_list_reports(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(default=None),
    _cur: CurrentUser = require_admin,
    db: AsyncSession = Depends(get_read_session),
) -> dict[str, Any]:
    """
    举报审核列表。可按状态过滤（pending/resolved/dismissed），倒序分页。
    """
    query = select(Report)
    count_q = select(func.count(Report.id))

    if status:
        query = query.where(Report.status == status)
        count_q = count_q.where(Report.status == status)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            query.order_by(Report.id.desc()).offset((page - 1) * size).limit(size)
        )
    ).scalars()

    items = [
        x.model_dump()
        for x in (
            AdminReportListItem(
                id=int(r.id),
                type=str(r.type),
                target_id=str(r.target_id),
                target_title=str(r.target_title),
                reporter_name=str(r.reporter_name),
                reason=str(r.reason),
                status=str(r.status),
                created_at=r.created_at,
                handled_at=r.handled_at,
            )
            for r in rows
        )
    ]

    return {"items": items, "total": total}
