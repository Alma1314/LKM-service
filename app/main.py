import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope
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
    import app.modules.columns.errors
    import app.modules.files.errors
    import app.modules.forum.errors
    import app.modules.members.errors
    import app.modules.starhope.errors


class _ImmutableStaticFiles(StaticFiles):
    """给静态文件成功响应附加 immutable 长缓存头。
    成员头像内容不变(文件名即未知指纹),浏览器/nginx/CDN 可永久缓存,与 /_astro/ 策略一致。
    404/错误响应不附加,避免把错误结果也缓存。
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if 200 <= response.status_code < 300:
            response.headers.setdefault(
                "cache-control",
                "public, max-age=31536000, immutable",
            )
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # 可观测基座：结构化日志 + Sentry APM（均幂等；DSN 空则不加载）
    logger.setup_logging()
    init_sentry()

    await init_db()

    # 启动即探测 Redis，便于日志暴露其状态（未配置/不可用时静默降级为 None）
    await redis_client.get_redis()

    # 确保成员头像静态目录存在（WebP 由运维/部署脚本放入）
    # mkdir 同步，放 to_thread 避免阻塞事件循环（ASYNC240）
    await asyncio.to_thread(
        lambda: Path(settings.avatars_dir).mkdir(parents=True, exist_ok=True)
    )

    cleanup_task = asyncio.create_task(cleanup_expired_challenges())

    yield

    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task

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

    # 成员头像静态文件：/static/avatars/*.webp，长缓存 immutable
    application.mount(
        "/static/avatars",
        _ImmutableStaticFiles(directory=settings.avatars_dir, check_dir=False),
        name="avatars",
    )

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"message": "OK"}

    return application


async def _on_err(_request: Request, exc: Exception) -> JSONResponse:
    _, errcode, detail = map_err(exc)
    return resp_json(errcode, detail=detail)


app = create_app()
