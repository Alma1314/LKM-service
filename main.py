from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import initdb
from err import BizError
from route import on_biz_error, router


@asynccontextmanager
async def lifespan(app: FastAPI):
    initdb()
    yield


app = FastAPI(title="LKM-API", version="0.0.1", lifespan=lifespan)
app.include_router(router)
app.add_exception_handler(BizError, on_biz_error)
