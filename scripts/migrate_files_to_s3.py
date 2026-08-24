"""一次性：把本地 ``files_store`` 存量导入 MinIO/S3。幂等，无数据时安全空跑。

存量本地文件按内容寻址 ``files_store_dir/<hash[:2]>/<hash>`` 落盘（``_build_bucket_key`` 形态），
S3 用同形 key + ``s3_prefix``（S3Storage 内部拼接 prefix）。本脚本用 storage 抽象 ``exists``
判断是否已在远端、再 ``save`` 搬运，并对 sha3 内容哈希做一致性校验（防中途损坏/改键）。

用法：``cd LKM-service && ./.venv/Scripts/python.exe -m scripts.migrate_files_to_s3``
需先配置好 ``storage_backend=s3`` 及 ``s3_*`` 连接参数。
"""

import asyncio
import hashlib
from pathlib import Path

# ruff: noqa: ASYNC240 一次性 CLI 迁移脚本：async 仅因 storage 抽象，本地 pathlib 批量读小文件
# 属一次性维护动作、非并发请求路径，阻塞 IO 可接受，无需换 anyio.Path。
from app.core.config import settings
from app.modules.storage.factory import get_storage


async def _migrate() -> None:
    root = Path(settings.files_store_dir)
    if not root.exists():
        print(f"[skip] {root} 不存在，无存量")
        return

    storage = get_storage()
    moved = 0
    for dest in sorted(p for p in root.rglob("**/*") if p.is_file()):
        rel = dest.relative_to(root).as_posix()  # 形如 <hash[:2]>/<hash>
        local_hash = hashlib.sha3_256(dest.read_bytes()).hexdigest()
        if local_hash != rel.split("/")[-1]:
            print(f"[warn] {rel} 内容哈希与文件名不符，跳过")
            continue
        if await storage.exists(rel):
            continue  # 幂等：已在远端
        with dest.open("rb") as fh:
            await storage.save(fh, max_bytes=settings.max_upload_bytes, bucket_key=rel)
        moved += 1
        print(f"[move] {rel}")

    print(f"done: {moved} files uploaded")


if __name__ == "__main__":
    asyncio.run(_migrate())
