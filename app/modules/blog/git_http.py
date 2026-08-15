import asyncio
import base64
import contextlib
import logging
import os
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_session
from app.modules.auth.security import verifypwd

logger = logging.getLogger(__name__)

git_router = APIRouter(prefix="/blog/git", tags=["blog-git"])


def _run_git_http_backend(env: dict[str, str], body: bytes) -> Response:
    """
    同步运行 git http-backend 并解析其输出。
    在 async 端点内通过 asyncio.to_thread 调度，避免长 git 传输（clone/push）阻塞事件循环。
    """
    try:
        proc = subprocess.Popen(
            ["git", "http-backend"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500, detail="git executable not found"
        ) from None

    try:
        stdout, _ = proc.communicate(input=body, timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise HTTPException(status_code=504, detail="Git operation timed out") from None

    header_end = stdout.find(b"\r\n\r\n")
    if header_end != -1:
        header_section = stdout[:header_end].decode("utf-8", errors="replace")
        response_body = stdout[header_end + 4 :]
    else:
        header_section = ""
        response_body = stdout

    status_code = 200
    content_type = "application/octet-stream"
    response_headers: dict[str, str] = {}

    for line in header_section.split("\r\n"):
        if line.lower().startswith("status:"):
            with contextlib.suppress(ValueError, IndexError):
                status_code = int(line.split(":", 1)[1].strip().split()[0])
        elif ":" in line:
            key, value = line.split(":", 1)
            response_headers[key.strip()] = value.strip()

    content_type = response_headers.pop("Content-Type", content_type)

    return Response(
        content=response_body,
        status_code=status_code,
        media_type=content_type,
        headers=response_headers,
    )


@git_router.api_route("/{repo_name}.git/{rest:path}", methods=["GET", "POST"])
async def git_http_backend(
    repo_name: str,
    rest: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> Response:
    root = str(await asyncio.to_thread(os.path.abspath, settings.blog_repo_dir))
    repo_path = os.path.join(root, f"{repo_name}.git")

    if not await asyncio.to_thread(os.path.isdir, repo_path):
        raise HTTPException(status_code=404, detail="Repository not found")

    env = os.environ.copy()
    env["GIT_PROJECT_ROOT"] = root
    env["GIT_HTTP_EXPORT_ALL"] = "1"
    env["PATH_INFO"] = f"/{repo_name}.git/{rest}"
    env["REQUEST_METHOD"] = request.method
    env["CONTENT_TYPE"] = request.headers.get("Content-Type", "")
    env["CONTENT_LENGTH"] = request.headers.get("Content-Length", "0")
    qs = str(request.url.query) if request.url.query else ""
    env["QUERY_STRING"] = qs

    # Basic Auth 校验（读权限门槛；会话由 FastAPI 依赖注入统一管理）
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            user = (
                (await db.execute(select(User).where(User.username == username)))
                .scalars()
                .first()
            )
            if user and verifypwd(password, user.hashed_password):
                env["REMOTE_USER"] = username
        except Exception as exc:
            logger.warning("git Basic Auth 校验失败，回退为匿名（读公开）: %s", exc)

    body = await request.body()

    # 长 git 传输（clone/push）是在线程中运行，避免阻塞事件循环
    return await asyncio.to_thread(_run_git_http_backend, env, body)
