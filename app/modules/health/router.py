from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core import redis as redis_client
from app.core.common import ApiResp
from app.core.err import respond
from app.db.session import get_async_engine

router = APIRouter(tags=["health"])


class DependencyStatus(BaseModel):
    status: str
    detail: str | None = None


class HealthData(BaseModel):
    status: str
    db: DependencyStatus
    redis: DependencyStatus


async def _probe_db() -> DependencyStatus:
    """探测数据库：执行 SELECT 1，失败返回 error（含 detail）。"""
    engine = get_async_engine()
    if engine is None:
        return DependencyStatus(status="error", detail="engine not initialized")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return DependencyStatus(status="up")
    except Exception as exc:
        return DependencyStatus(status="error", detail=str(exc))


async def _probe_redis() -> DependencyStatus:
    """探测 Redis：get_redis 未配置/不可用返回 None → disabled；可用则 up。"""
    client = await redis_client.get_redis()
    if client is None:
        return DependencyStatus(status="disabled", detail="redis_url 未配置或不可用")
    try:
        ok = await client.ping()
    except Exception as exc:
        return DependencyStatus(status="error", detail=str(exc))
    if not ok:
        return DependencyStatus(status="error", detail="ping failed")
    return DependencyStatus(status="up")


@router.get("/health", response_model=ApiResp[HealthData])
@respond
async def health_check() -> dict[str, object]:
    """健康检查：聚合 DB 与 Redis 状态，供探活与可观测基座使用。"""
    db_status = await _probe_db()
    redis_status = await _probe_redis()
    overall = (
        "ok" if db_status.status == "up" and redis_status.status == "up" else "degraded"
    )
    return {
        "status": overall,
        "db": db_status,
        "redis": redis_status,
    }
