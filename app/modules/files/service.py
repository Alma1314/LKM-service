import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError
from app.modules.files.errors import FileErr
from app.db.models import LibraryFile, User
from app.db.repo import get_or_raise
from app.modules.files.models import FILES_TABLE_PLAN
from app.modules.files.schemas import FileCreate, FileInfo, PageData


class _Readable(Protocol):
    """可同步分块读取的 file-like 对象最小协议。"""

    def read(self, size: int = -1, /) -> bytes: ...


def get_files_plan() -> dict[str, Any]:
    return {
        "status": "implemented_minimal",
        "tables": FILES_TABLE_PLAN,
        "next_steps": [
            "Add review approval workflow",
            "Add duplicate / plagiarism detection",
            "Add file serving with presigned URL",
        ],
    }


def _uploader_name(user: User) -> str:
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return user.username


def _file_to_schema(f: LibraryFile, uploader_name: str) -> FileInfo:
    return FileInfo.model_validate(f).model_copy(update={"uploader_name": uploader_name})


async def _uploader_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User).where(User.id.in_(set(user_ids))).options(selectinload(User.profile))
    )
    users = result.scalars().all()
    return {u.id: _uploader_name(u) for u in users}


def _make_stored_name(original_name: str) -> str:
    suffix = Path(original_name).suffix[:32]
    return f"{uuid.uuid4().hex}{suffix}"


async def list_files(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    category_id: str | None = None,
    status: str | None = None,
    sort: str = "newest",
) -> PageData[FileInfo]:
    base = select(LibraryFile)
    if category_id:
        base = base.where(LibraryFile.category_id == category_id)
    if status:
        base = base.where(LibraryFile.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    order = LibraryFile.download_count.desc() if sort == "downloads" else LibraryFile.id.desc()
    files = (
        await db.execute(base.order_by(order).offset((page - 1) * limit).limit(limit))
    ).scalars().all()

    names = await _uploader_map(db, [f.uploader_id for f in files])
    items = [_file_to_schema(f, names.get(f.uploader_id, "")) for f in files]
    return PageData(items=items, total=total, page=page, pages=(total + limit - 1) // limit)


async def get_file(db: AsyncSession, file_id: int, bump_view: bool = False) -> FileInfo:
    f = await get_or_raise(db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id)

    if bump_view:
        f.view_count += 1
        await db.flush()

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))


_CHUNK = 1024 * 1024  # 分块读写，避免整文件载入内存


def _stream_to_disk(stream: _Readable, dest_path: Path, limit: int) -> int:
    """
    同步分块读取 ``stream`` 并写盘，返回总字节数。
    在 async 端点内通过 asyncio.to_thread 调度，避免文件读写（含建目录）阻塞事件循环。
    超过 ``limit`` 抛 ``FILE_TOO_LARGE``；OS 错误抛 ``FileErr.STORE_ERROR``。
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with dest_path.open("wb") as out:
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise BizError(
                    FileErr.TOO_LARGE,
                    detail=f"Upload exceeds {limit} byte limit",
                )
            out.write(chunk)
    return total


async def _write_upload(stream: _Readable, dest: Path, limit: int) -> int:
    try:
        return await asyncio.to_thread(_stream_to_disk, stream, dest, limit)
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise BizError(FileErr.STORE_ERROR, detail=f"Failed to store file: {exc}") from exc


async def create_file(
    db: AsyncSession,
    uploader_id: int,
    info: FileCreate,
    stream: _Readable,
    max_bytes: int | None = None,
) -> FileInfo:
    """把上传流分块落盘并登记元数据。

    ``stream`` 需提供 ``read(n)``（可同步 File 对象）。累计超过 ``max_bytes``（默认取配置值）
    立即中止并抛 ``FILE_TOO_LARGE``，不留下磁盘文件。落盘在后台线程执行，避免阻塞事件循环。
    """
    limit = max_bytes or settings.max_upload_bytes
    stored_name = _make_stored_name(info.original_name)
    dest = Path(settings.files_store_dir) / stored_name

    try:
        total = await _write_upload(stream, dest, limit)
    except BizError:
        dest.unlink(missing_ok=True)
        raise

    try:
        f = LibraryFile(
            uploader_id=uploader_id,
            original_name=info.original_name,
            stored_name=stored_name,
            mime_type=info.mime_type,
            size=total,
            category_id=info.category_id,
            description=info.description,
            tags=json.dumps(info.tags, ensure_ascii=False),
        )
        db.add(f)
        await db.flush()
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))


async def bump_download(db: AsyncSession, file_id: int) -> int:
    f = await get_or_raise(db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id)
    f.download_count += 1
    await db.flush()
    return f.download_count
