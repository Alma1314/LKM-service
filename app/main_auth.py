"""B1.1 AUTH 独立 ASGI 进程入口：auth 域自有、与单体并行的读/认证面。

背景（M3 B1）：A1-A7 已把 auth 身份读面收敛进 monolith 内的 ``auth.snapshot`` 读缝
并给出 ``user:snap`` 缓存；B1 把该 AUTH 读对外化为独立进程的第一步 —— 先给一个
**可独立运行的 auth-only ASGI 应用** + 它**专属的 liveness/readiness 健康缝** + compose
同镜像异 command 的 ``auth`` 服务。纯增量，不改单体 ``app.main`` 任何行为。
B1.2 在同进程再挂 internal 读缝 router（``auth.router_read``，/auth/internal，B1.2 seam），
令 AUTH 进程本身也能 serve 该读端点供消费进程经 HTTP 跨缝（nginx 路由 B1.3 接）。

装配口径：此进程只 mount ``app.modules.auth`` 的 7 个 router（登录/档案/2FA/oauth/
passkey/recovery/settings）**plus** 本进程自己的 auth-health router；不引业务域
（content/feed/points/projects 等）、不起 GraphQL/WebSocket、不做制品迁移 —— auth 是
owner-leaf，其 router 只依赖 core + db.session + auth 内部，故可干净独立装配。
进程内 HTTP 面对外暴露（nginx location / B1.3 复合就绪合并）属后续 leg，此处仅就绪
一个可被 compose/后续编排单独探活的自足进程。

同名但独立：DB 引擎/Redis client 由本进程内 realm 各自 lazy 自持（同库同数据源，
进程隔离）。lifespan 不起 alembic 迁移（避免与单体并发迁移）；仅做退出清理。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import app.health_auth as health_auth
from app.core import redis as redis_client
from app.core.config import settings
from app.core.err import BizError, map_err, resp_json
from app.db.session import dispose_engine
from app.modules.auth import router as auth_router
from app.modules.auth import (
    router_2fa,
    router_oauth,
    router_onboarding,
    router_passkey,
    router_read,
    router_recovery,
    router_settings,
)

# 本进程装配的 auth 面（子集口径见模块 docstring）：独立于业务 registry，
# 显式 import 各 auth router 聚合，不触发非 auth 模块副作用。
_AUTH_ROUTERS = [
    auth_router.router,
    router_2fa.router,
    router_oauth.router,
    router_onboarding.router,
    router_passkey.router,
    router_read.router,  # B1.2：AUTH 进程同样 serve 内部读缝（供消费进程序扣真值/sv）
    router_recovery.router,
    router_settings.router,
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # 只读/认证读进程：DB 引擎与 Redis 均 lazy 自持，不起 alembic 迁移
    # （迁移由单体的 backend 进程负责，避免 auth 进程与其并发 migrate）。
    try:
        yield
    finally:
        # 退出清理：dispose engine / close redis，进程收尾不泄漏连接
        await dispose_engine()
        await redis_client.close_redis()


def create_auth_app() -> FastAPI:
    """装配 auth-only ASGI 应用。不调 registry.load_all / 不起 GraphQL / 不挂 /metrics。"""
    application = FastAPI(
        title=f"{settings.app_name}-auth",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # 与单体一致的 error 语义映射（BizError / 校验错误 / 兜底 500），保证 auth 端点错误口径一致
    application.add_exception_handler(BizError, _on_err)
    application.add_exception_handler(RequestValidationError, _on_err)
    application.add_exception_handler(Exception, _on_err)

    # mount auth 域面 + 本进程健康面（健康面不经 api_prefix，供编排直接命中）
    for _r in _AUTH_ROUTERS:
        application.include_router(_r, prefix=settings.api_prefix)
    application.include_router(health_auth.router)

    return application


async def _on_err(_request: Request, exc: Exception) -> JSONResponse:
    _, errcode, detail = map_err(exc)
    return resp_json(errcode, detail=detail)


app = create_auth_app()


def main() -> None:
    """compose `python -m app.main_auth` 入口：起本进程自己的 uvicorn（内网端口）。

    只跑本 ASGI app，单 worker；host 0.0.0.0 + 固定内网端口 8001，
    由 compose auth 服务 def 面内部承载（无主机端口映射），B1.2 再交由 nginx 反代。
    """
    import uvicorn

    uvicorn.run(
        "app.main_auth:app",
        host="0.0.0.0",
        port=8001,
        log_level="info",
    )


if __name__ == "__main__":
    main()
