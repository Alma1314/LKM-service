"""一次性：把预置成员头像 ``static/avatars/*.webp`` 迁入 MinIO/S3。幂等。

预置头像按 ``avatars/{name}.webp`` 存 storage key（与 ``/api/v1/avatars/{name}`` 代理端点一致）。
头像文件名是成员名（非内容哈希），故不做哈希名校验，仅按 key 存在性幂等跳过。无目录时空跑。

用法：``cd LKM-service && ./.venv/Scripts/python.exe -m scripts.migrate_avatars_to_s3``
需先配置好 ``storage_backend=s3`` 及 ``s3_*`` 连接参数。
"""

import asyncio
from pathlib import Path

# ruff: noqa: ASYNC240 一次性 CLI 迁移脚本：async 仅因 storage 抽象，本地 pathlib 批量读小文件
# 属一次性维护动作、非并发请求路径，阻塞 IO 可接受，无需换 anyio.Path。
from app.core.config import settings
from app.modules.storage.factory import get_storage

_PRESET_PREFIX = "avatars"


async def _migrate() -> None:
    root = Path(settings.avatars_dir)
    if not root.exists():
        print(f"[skip] {root} 不存在，无预置头像")
        return

    if settings.storage_backend != "s3" and not Path(settings.files_store_dir).exists():
        # local 后端若无 store 根目录无法写入临时文件；迁移目标应是 S3，缺 S3 配置时明确提示
        import sys

        print(
            f"[error] storage_backend={settings.storage_backend!r} 且 {settings.files_store_dir} 不存在；"
            "迁移目标是 S3，请先配置 LKM_STORAGE_BACKEND=s3 及 s3_*。"
        )
        sys.exit(1)

    storage = get_storage()
    moved = 0
    for f in sorted(root.glob("*.webp")):
        key = f"{_PRESET_PREFIX}/{f.name}"
        if await storage.exists(key):
            continue  # 幂等：已在远端
        with f.open("rb") as fh:
            await storage.save(fh, max_bytes=settings.max_upload_bytes, bucket_key=key)
        moved += 1
        print(f"[move] {key}")

    print(f"done: {moved} avatars uploaded to {_PRESET_PREFIX}/")


if __name__ == "__main__":
    asyncio.run(_migrate())
