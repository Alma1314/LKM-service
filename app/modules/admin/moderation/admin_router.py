"""后台审校规则管理：/admin/moderation/rules 增删改查。

读列表走 ``require_admin``；写（增/改/删）属危险操作，走 ``require_admin_2fa``
（与 admin 其它写端点的 step-up 一致）。写后经 service 层 bump 规则缓存版本。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.admin.deps import require_admin, require_admin_2fa
from app.modules.admin.moderation import service as mod_service
from app.modules.admin.moderation.schemas import (
    RuleCreate,
    RuleInfo,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
)
from app.modules.auth.deps import CurrentUser
from app.modules.common import ApiResp, ListData

router = APIRouter(prefix="/admin/moderation", tags=["admin-moderation"])


@router.get("/rules", response_model=ApiResp[ListData[RuleInfo]])
@respond
async def admin_list_moderation_rules(
    _cur: CurrentUser = require_admin,
    db: AsyncSession = Depends(get_session),
) -> dict[str, list[RuleInfo]]:
    return {"items": await mod_service.list_rules(db)}


@router.post("/rules", response_model=ApiResp[RuleInfo])
@respond
async def admin_create_moderation_rule(
    info: RuleCreate,
    _cur: CurrentUser = require_admin_2fa,
    db: AsyncSession = Depends(get_session),
) -> RuleInfo:
    return await mod_service.create_rule(db, info)


@router.patch("/rules/{rule_id}", response_model=ApiResp[RuleInfo])
@respond
async def admin_update_moderation_rule(
    rule_id: int,
    info: RuleUpdate,
    _cur: CurrentUser = require_admin_2fa,
    db: AsyncSession = Depends(get_session),
) -> RuleInfo:
    return await mod_service.update_rule(db, rule_id, info)


@router.delete("/rules/{rule_id}", response_model=ApiResp[dict[str, bool]])
@respond
async def admin_delete_moderation_rule(
    rule_id: int,
    _cur: CurrentUser = require_admin_2fa,
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    await mod_service.delete_rule(db, rule_id)
    return {"ok": True}


@router.post("/rules/test", response_model=ApiResp[RuleTestResult])
@respond
async def admin_test_moderation_rules(
    req: RuleTestRequest,
    _cur: CurrentUser = require_admin_2fa,
    db: AsyncSession = Depends(get_session),
) -> RuleTestResult:
    return await mod_service.test_rules(db, req.text)
