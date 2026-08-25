import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response
from strawberry.fastapi import GraphQLRouter

from app.api.router import api_router
from app.core import logging as logger
from app.core import redis as redis_client
from app.core.apm import init_sentry
from app.core.config import settings
from app.core.err import BizError, map_err, resp_json
from app.db.init_db import init_db
from app.db.session import (
    AsyncSession,
    dispose_engine,
)
from app.db.session import (
    get_read_session as get_graphql_session,  # GraphQL 仅 Query(纯读)，避免空提交
)
from app.modules.auth.service_passkey import cleanup_expired_challenges
from app.modules.forum.graphql import GraphQLContext
from app.modules.forum.graphql import schema as forum_graphql_schema
from app.ws.manager import manager

request_logger = logging.getLogger("lkm.http")


def _register_all_errors() -> None:
    """错误码注册收敛：集中 import 各模块 errors 使 `register()` 副作用必达。
    防止漏配错误码导致 map_err 转 500。新增模块的 ErrCode 必须在此登记。导入放函数内
    （非模块顶层 `import app.x`），避免在 main 模块命名空间绑定 `app` 包名，与
    模块级 `app = create_app()` 冲突。
    """
    import app.modules.articles.errors
    import app.modules.auth.errors
    import app.modules.blog.errors
    import app.modules.boards.errors
    import app.modules.columns.errors
    import app.modules.exam.errors
    import app.modules.files.errors
    import app.modules.forum.errors
    import app.modules.points.errors
    import app.modules.projects.errors
    import app.modules.qa.errors
    import app.modules.starhope.errors


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # 可观测基座：结构化日志 + Sentry APM（均幂等；DSN 空则不加载）
    logger.setup_logging()
    init_sentry()

    await init_db()

    # 启动即探测 Redis，便于日志暴露其状态（未配置/不可用时静默降级为 None）
    await redis_client.get_redis()

    cleanup_task = asyncio.create_task(cleanup_expired_challenges())

    yield

    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task

    # 收尾 WebSocket 事件的 Redis 订阅 task，避免泄漏连接
    await manager.close()

    await redis_client.close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    # 确保所有错误码已注册（防漏配导致 500）
    _register_all_errors()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def _log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """结构化访问日志：注入 request_id，记录 method/route/status/latency。"""
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = logger.set_request_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            latency_ms = (time.perf_counter() - start) * 1000
            response.headers.setdefault("X-Request-ID", request_id)
            request_logger.info(
                "http.request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "route": request.url.path,
                        "status": response.status_code,
                        "latency_ms": round(latency_ms, 3),
                    }
                },
            )
            return response
        finally:
            logger.reset_request_id(token)

    application.include_router(api_router, prefix=settings.api_prefix)
    application.add_exception_handler(BizError, _on_err)
    application.add_exception_handler(RequestValidationError, _on_err)
    application.add_exception_handler(Exception, _on_err)

    async def _graphql_context(
        db: AsyncSession = Depends(get_graphql_session),
    ) -> GraphQLContext:
        # 会话生命周期由 FastAPI 的 Depends 管理，解析器只读不关闭
        return GraphQLContext(db=db)

    graphql_router = GraphQLRouter(
        forum_graphql_schema,
        path="/graphql",
        context_getter=_graphql_context,
    )
    application.include_router(graphql_router)

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"message": "OK"}

    return application


async def _on_err(_request: Request, exc: Exception) -> JSONResponse:
    _, errcode, detail = map_err(exc)
    return resp_json(errcode, detail=detail)


app = create_app()
