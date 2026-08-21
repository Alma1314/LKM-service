"""存储后端抽象接口：``StorageBackend`` 协议 + ``SavedFile`` 记录。

``StorageBackend`` 是 Local/S3 两个后端共同遵循的最小协议（save/open/delete/exists +
预签名），files 层依赖该协议而非具体后端实现。
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol, TypedDict


class SavedFile(TypedDict, total=False):
    size: int
    bucket_key: str
    storage_path: str


class StorageBackend(Protocol):
    async def save(
        self, stream: Any, /, *, max_bytes: int, bucket_key: str
    ) -> SavedFile: ...

    # 异步生成器方法：真实后端经 `async def open(...) ... yield` 实现，其可调用类型为
    # Callable 返回 AsyncIterator[bytes]；故协议用普通 def（非 async）标注生成器函数形态，
    # 使 AsyncGenerator <: AsyncIterator 满足结构兼容（async def + body=`...` 会被 ty 当协程返回，不匹配）
    def open(self, bucket_key: str) -> AsyncIterator[bytes]: ...

    async def copy(self, src: str, dest: str) -> None: ...

    async def delete(self, bucket_key: str) -> None: ...

    async def exists(self, bucket_key: str) -> bool: ...

    def presign_download(self, bucket_key: str, *, expires: int) -> str: ...

    def presign_upload(self, bucket_key: str, *, expires: int) -> str: ...
