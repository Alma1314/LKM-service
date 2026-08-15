import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await init_db()

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

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"message": "OK"}

    return application


async def _on_err(_request: Request, exc: Exception) -> JSONResponse:
    _, errcode, detail = map_err(exc)
    return resp_json(errcode, detail=detail)


app = create_app()
