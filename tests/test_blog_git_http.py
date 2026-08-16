"""blog git smart HTTP 的 Basic Auth 解析与端点行为测试。

覆盖：_decode_basic_auth 的格式解析（有效/无效 base64/缺冒号/非 UTF-8/非 Basic 头），
以及 Basic Auth 校验失败时回退匿名读、DB 错误正常传播（不吞异常）。
"""

import base64
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.modules.blog.git_http import _decode_basic_auth


class TestDecodeBasicAuth:
    def should_parse_valid_credentials(self):
        token = base64.b64encode(b"user:pass").decode()
        assert _decode_basic_auth(f"Basic {token}") == ("user", "pass")

    def should_parse_password_containing_colon(self):
        token = base64.b64encode(b"user:pa:ss").decode()
        assert _decode_basic_auth(f"Basic {token}") == ("user", "pa:ss")

    def should_return_none_for_invalid_base64(self):
        assert _decode_basic_auth("Basic !!!not-base64!!!") is None

    def should_return_none_for_missing_colon(self):
        token = base64.b64encode(b"usernocolon").decode()
        assert _decode_basic_auth(f"Basic {token}") is None

    def should_return_none_for_non_utf8_bytes(self):
        # b"\xff\xfe" 不是合法 UTF-8，decode 会抛 UnicodeDecodeError
        token = base64.b64encode(b"\xff\xfe").decode()
        assert _decode_basic_auth(f"Basic {token}") is None

    def should_return_none_for_non_basic_scheme(self):
        assert _decode_basic_auth("Bearer abc") is None
        assert _decode_basic_auth("") is None


class _FakeDbError:
    """模拟 DB 故障：execute 抛运行时错误。"""

    async def execute(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("db down")


class _FakeRequest:
    method = "GET"
    headers: ClassVar[dict[str, str]] = {
        "Authorization": "Basic " + base64.b64encode(b"user:pass").decode()
    }
    url = SimpleNamespace(query="")

    async def body(self) -> bytes:
        return b""


class TestGitHttpDbErrorPropagates:
    async def should_propagate_db_error_instead_of_swallowing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        """Basic Auth 的 DB 查询失败应正常传播，而非被 except Exception 吞成匿名读。"""
        import os

        from app.core.config import settings
        from app.modules.blog.git_http import git_http_backend

        repo_dir = str(tmp_path / "blog_repos")
        monkeypatch.setattr(settings, "blog_repo_dir", repo_dir)
        # 端点先检查 repo 目录存在才进入 Basic Auth 校验，故需先建目录
        os.makedirs(os.path.join(repo_dir, "my-blog.git"))

        with pytest.raises(RuntimeError, match="db down"):
            await git_http_backend(
                "my-blog",
                "info/refs",
                _FakeRequest(),  # type: ignore
                _FakeDbError(),  # type: ignore
            )


class _BodyCalledError(Exception):
    pass


class _FakeStreamRequest:
    method = "GET"
    headers: ClassVar[dict[str, str]] = {}
    url = SimpleNamespace(query="")

    async def body(self) -> bytes:
        raise _BodyCalledError("request.body() should not be called")

    async def stream(self):
        # 空流：GET（clone）无请求体
        if False:
            yield b""


class TestGitHttpStreamsBody:
    async def should_use_stream_instead_of_body(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        """请求体应经 request.stream() 流式喂入，而非 request.body() 全量缓冲。"""
        import os

        from app.core.config import settings
        from app.modules.blog.git_http import git_http_backend

        repo_dir = str(tmp_path / "blog_repos")
        monkeypatch.setattr(settings, "blog_repo_dir", repo_dir)
        os.makedirs(os.path.join(repo_dir, "my-blog.git"))

        try:
            await git_http_backend(
                "my-blog",
                "info/refs",
                _FakeStreamRequest(),  # type: ignore
                None,  # type: ignore  # 无 Authorization 头，不会访问 db
            )
        except _BodyCalledError:
            pytest.fail("git_http_backend 仍调用 request.body()，应改用 stream() 流式")
