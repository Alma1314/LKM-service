from typing import Any

from fastapi import APIRouter, Query

from app.core.err import respond
from app.modules.common import ApiResp, ListData
from app.modules.members.models import ALL_TYPES, SUB_GROUP_MAPS
from app.modules.members.schemas import Member, SubGroupItem
from app.modules.members.service import get_members, get_sub_groups

router = APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=ApiResp[ListData[Member]])
@respond
async def get_member_list(
    type: str = Query(..., description=f"数据组标识，可选：{', '.join(ALL_TYPES)}"),
    group: str | None = Query(None, description="子组标识，仅 subGroupMaps 需要"),
) -> dict[str, Any]:
    return get_members(type, group).model_dump()


@router.get("/subgroups", response_model=ApiResp[ListData[SubGroupItem]])
@respond
async def get_member_subgroups(
    type: str = Query(
        ...,
        description=f"子组集合标识，可选：{', '.join(sorted(SUB_GROUP_MAPS.keys()))}",
    ),
) -> dict[str, Any]:
    """返回某 subGroupMap 类型的完整分组结构（含 label/desc/members）。"""
    return get_sub_groups(type).model_dump()
