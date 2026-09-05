from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core import redis as redis_client
from app.core.common import ApiResp
from app.core.config import settings
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
    auth: DependencyStatus


# AUTH 活性的可注入出站 client 工厂（monolith 就绪探针用）：默认 None → 按配置超时新建
# httpx client 打 AUTH 进程 /liveness；测试经 monkeypatch 换成返回假 transport 的 client
# 即可离线端到端驱动（与 auth.user_http._client_factory 同款范式）。
_auth_liveness_factory: Any = None


async def _probe_auth() -> DependencyStatus:
    """AUTH 依赖可选探针（M3 B1.3）：仅当配置了 ``auth_http_url`` 才探，否则 disabled。

    单进程默认(auth_http_url 为空) → disabled 且不影响 overall —— monolith 与 AUTH 同进程
    部署时本体不声明任何对外 auth 依赖，就绪语义与既存完全一致。配置了(独立 AUTH 进程反代
    接出)才反映 AUTH 可达性：GET ``<auth_http_url>/liveness``（AUTH 自足存活端点，零级联其
    DB/Redis），失败/超时 → error(降级)。超时受配置 ``auth_http_timeout_s`` 上界约束，绝不让
    一个不可达的 AUTH 把 monolith 就绪探针挂死在连接等待上；本模块的 liveness 面不受影响。
    """
    base = (settings.auth_http_url or "").strip().rstrip("/")
    if not base:
        return DependencyStatus(status="disabled", detail="auth_http_url 未配置")
    url = f"{base}/liveness"
    try:
        async with _build_auth_client() as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return DependencyStatus(status="error", detail=f"auth 不可达: {exc}")
    if resp.status_code != 200:
        return DependencyStatus(status="error", detail=f"auth /liveness http {resp.status_code}")
    payload = _coerce_liveness(resp)
    ok = isinstance(payload, dict) and payload.get("status") == "ok"
    if not ok:
        return DependencyStatus(status="error", detail="auth /liveness 未返回 ok")
    return DependencyStatus(status="up")


def _build_auth_client() -> httpx.AsyncClient:
    """每探测级 client + 配置超时（与 auth.user_http._build_client 同款出站风格）。"""
    if _auth_liveness_factory is not None:
        return _auth_liveness_factory()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.auth_http_timeout_s,
            read=settings.auth_http_timeout_s,
            write=settings.auth_http_timeout_s,
            pool=settings.auth_http_timeout_s,
        )
    )


def _coerce_liveness(resp: httpx.Response) -> dict[str, object] | None:
    """/liveness 响应 → dict；非 JSON/非对象 → None（探针把其当作非 ok，不抛）。"""
    try:
        parsed = resp.json()
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


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
    """健康检查：聚合 DB、Redis 与(可选)AUTH 状态，供探活与可观测基座使用。

    AUTH 探针仅在配置 ``auth_http_url``(独立 AUTH 进程接出)时参与降级判定；默认空 →
    ``auth.disabled`` 不参与，overall 只取决于 DB+Redis，保持既存单进程就绪语义零变化。
    """
    db_status = await _probe_db()
    redis_status = await _probe_redis()
    auth_status = await _probe_auth()
    overall = (
        "ok"
        if db_status.status == "up"
        and redis_status.status == "up"
        and (auth_status.status == "up" or auth_status.status == "disabled")
        else "degraded"
    )
    return {
        "status": overall,
        "db": db_status,
        "redis": redis_status,
        "auth": auth_status,
    }
