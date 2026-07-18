from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.boards.router import router as boards_router
from app.modules.columns.router import router as columns_router
from app.modules.health.router import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(boards_router)
api_router.include_router(columns_router)
