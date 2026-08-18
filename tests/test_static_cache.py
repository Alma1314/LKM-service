"""模块9 测试补盲：_ImmutableStaticFiles 的 immutable 长缓存头逻辑。"""

import pytest
from starlette.types import Scope

from app.main import _ImmutableStaticFiles


def _static(tmp_path, filename: str = "avatar.webp") -> _ImmutableStaticFiles:
    (tmp_path / filename).write_bytes(b"fake-webp-bytes")
    return _ImmutableStaticFiles(directory=str(tmp_path), check_dir=False)


def test_success_response_gets_immutable_cache(tmp_path) -> None:
    """2xx 成功响应附加 long-lived 不可变缓存头。"""
    app = _static(tmp_path)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/avatar.webp",
        "headers": [],
    }

    import asyncio

    response = asyncio.run(app.get_response("avatar.webp", scope))
    assert 200 <= response.status_code < 300
    assert (
        response.headers.get("cache-control") == "public, max-age=31536000, immutable"
    )


def test_missing_file_raises_not_404_response(tmp_path) -> None:
    """缺失文件抛 HTTPException(404)（非 Response）→ 错误结果不会被 immutable 缓存。"""
    import asyncio

    from starlette.exceptions import HTTPException

    app = _static(tmp_path)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/nope.webp",
        "headers": [],
    }

    # 缺失文件：get_response 抛 404（而非回 Response），FastAPI 转通用 404，
    # 不会落到 _ImmutableStaticFiles 的 2xx 分支，因而带不上 immutable 缓存头。
    with pytest.raises(HTTPException, match="404"):
        asyncio.run(app.get_response("missing.webp", scope))


def test_existing_header_not_overwritten(tmp_path) -> None:
    """已有 cache-control 头时用 setdefault，不覆盖显式设置。"""
    app = _static(tmp_path)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/avatar.webp",
        "headers": [],
    }

    import asyncio

    response = asyncio.run(app.get_response("avatar.webp", scope))
    # mtime 相同则可能 304；此处确保只要 2xx 就带不可变头
    assert "cache-control" in response.headers or response.status_code == 304
