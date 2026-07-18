from pydantic import BaseModel

from fastapi import APIRouter

from app.core.err import respond
from app.modules.common import ApiResp

router = APIRouter(tags=["health"])


class HealthData(BaseModel):
    status: str


@router.get("/health", response_model=ApiResp[HealthData])
@respond
async def health_check():
    return {"status": "ok"}
