from fastapi import APIRouter

from app.modules.admin.auth_router import router as admin_router
from app.modules.admin.content_router import router as admin_content_router
from app.modules.admin.reports_router import router as admin_reports_router
from app.modules.admin.users_router import router as admin_data_router
from app.modules.articles.router import router as articles_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.router_2fa import router as auth_2fa_router
from app.modules.auth.router_oauth import router as auth_oauth_router
from app.modules.auth.router_passkey import router as auth_passkey_router
from app.modules.auth.router_recovery import router as auth_recovery_router
from app.modules.auth.router_settings import router as auth_settings_router
from app.modules.blog.git_http import git_router
from app.modules.blog.router import router as blog_router
from app.modules.boards.router import router as boards_router
from app.modules.columns.router import router as columns_router
from app.modules.exam.router import router as exam_router
from app.modules.files.notify import router as files_notify_router
from app.modules.files.router import router as files_router
from app.modules.forum.router import router as forum_router
from app.modules.health.router import router as health_router
from app.modules.members.avatar_router import router as avatars_router
from app.modules.members.router import router as members_router
from app.modules.points.router import router as points_router
from app.modules.projects.router import router as projects_router
from app.modules.qa.router import router as qa_router
from app.modules.starhope.router import router as starhope_router
from app.ws.router import router as ws_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(members_router)
api_router.include_router(avatars_router)
api_router.include_router(admin_router)
api_router.include_router(admin_content_router)
api_router.include_router(admin_data_router)
api_router.include_router(admin_reports_router)
api_router.include_router(auth_router)
api_router.include_router(auth_2fa_router)
api_router.include_router(auth_oauth_router)
api_router.include_router(auth_passkey_router)
api_router.include_router(auth_recovery_router)
api_router.include_router(auth_settings_router)
api_router.include_router(boards_router)
api_router.include_router(columns_router)
api_router.include_router(exam_router)
api_router.include_router(forum_router)
api_router.include_router(files_router)
api_router.include_router(files_notify_router)
api_router.include_router(blog_router)
api_router.include_router(articles_router)
api_router.include_router(git_router)
api_router.include_router(points_router)
api_router.include_router(projects_router)
api_router.include_router(qa_router)
api_router.include_router(starhope_router)
api_router.include_router(ws_router)
