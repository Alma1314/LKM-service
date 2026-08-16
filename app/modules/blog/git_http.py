import asyncio
import base64
import binascii
import contextlib
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_session
from app.modules.auth.security import verifypwd

logger = logging.getLogger(__name__)

git_router = APIRouter(prefix="/blog/git", tags=["blog-git"])


def _decode_basic_auth(header: str) -> tuple[str, str] | None:
    """解析 Basic Authorization 头为 (username, password)。

    仅当 header 为合法 Basic 凭据时返回元组；base64 解码失败、非 UTF-8、
    缺少冒号等格式错误返回 None，由调用方回退匿名读。
    """
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return username, password


def _parse_git_response(stdout: bytes) -> Response:
    """解析 git http-backend 的 CGI 输出为 HTTP Response。"""
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


async def _stream_to_stdin(proc: asyncio.subprocess.Process, request: Request) -> None:
    """把请求体流式写入 git http-backend 的 stdin，写完关闭 stdin。"""
    assert proc.stdin is not None
    try:
        async for chunk in request.stream():
            proc.stdin.write(chunk)
            await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        # 进程可能已提前退出（如 push 被拒），写失败可忽略
        pass
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()


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
    creds = _decode_basic_auth(auth)
    if creds is not None:
        username, password = creds
        user = (
            (await db.execute(select(User).where(User.username == username)))
            .scalars()
            .first()
        )
        if user and await verifypwd(password, user.hashed_password):
            env["REMOTE_USER"] = username
    elif auth.startswith("Basic "):
        # 仅格式错误（非 base64/缺冒号/非 UTF-8）回退匿名读；DB/内部错误不在此捕获，正常传播
        logger.warning("git Basic Auth 格式无效，回退为匿名（读公开）")

    # 用 asyncio 子进程 + request.stream() 流式喂入请求体，避免 request.body() 全量缓冲
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "http-backend",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500, detail="git executable not found"
        ) from None

    try:
        async with asyncio.timeout(120):
            await _stream_to_stdin(proc, request)
            stdout, _ = await proc.communicate()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail="Git operation timed out") from None

    return _parse_git_response(stdout)
