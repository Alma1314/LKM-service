from fastapi import APIRouter

from app.core.err import respond
from app.modules.common import ApiResp

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResp)
@respond
async def health_check():
    return {"status": "ok"}
