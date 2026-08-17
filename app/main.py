import asyncio
from collections.abc import AsyncGenerator
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
from app.core.config import settings
from app.core.err import BizError, map_err, resp_json
from app.db.init_db import init_db
from app.db.session import (
    AsyncSession,
    dispose_engine,
)
from app.db.session import (
    get_session as get_graphql_session,
)
from app.modules.auth.service_passkey import cleanup_expired_challenges
from app.modules.forum.graphql import GraphQLContext
from app.modules.forum.graphql import schema as forum_graphql_schema


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
    await init_db()

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

    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
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
